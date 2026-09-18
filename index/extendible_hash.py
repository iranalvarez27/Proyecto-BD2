import os
import struct
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import RID
from engine.buffer_pool import BufferPool
from engine.segment import NIL, Segment
from index.base import Index
from index.bucket_page import (
    MAX_ENTRIES,
    PAGE_KIND_OVERFLOW,
    PAGE_KIND_PRIMARY,
    PAGE_SIZE,
    BucketPage,
)
from index.hash_utils import stable_hash

HASH_BITS = 64  # stable_hash() returns a 64-bit value

META_PAGE = 0
# global_depth | flags | bucket_capacity | pad | first_dir_page | free_list_head
META_FORMAT = "<BBHHii"

# Directory pages: a next-page link, then a run of bucket page ids.
DIR_HEADER_FORMAT = "<i"
DIR_HEADER_SIZE = struct.calcsize(DIR_HEADER_FORMAT)  # 4
ENTRIES_PER_DIR_PAGE = (PAGE_SIZE - DIR_HEADER_SIZE) // 4  # 1023


class ExtendibleHash(Index):
    def __init__(self, pool: BufferPool, path: str, bucket_capacity: int = MAX_ENTRIES):
        self._seg = Segment(pool, path)
        if self._seg.page_count() > 0:
            self._load()
        else:
            if not 1 <= bucket_capacity <= MAX_ENTRIES:
                raise ValueError(f"bucket_capacity must be in [1, {MAX_ENTRIES}]")
            self._create(bucket_capacity)

    # ------------------------------------------------------------------ Index

    def insert(self, key: Any, rid: RID) -> None:
        self._insert_hash(stable_hash(key), rid)

    def search(self, key: Any) -> list[RID]:
        key_hash = stable_hash(key)
        out: list[RID] = []
        page_id = self._dir[key_hash & self._mask()]
        while page_id != NIL:
            page = self._read_bucket(page_id)
            out.extend(rid for h, rid in page.entries if h == key_hash)
            page_id = page.overflow_page_id
        return out

    def range_search(self, low: Any, high: Any) -> list[RID]:
        raise NotImplementedError(
            "ExtendibleHash does not support range queries"
        )

    def delete(self, key: Any, rid: RID) -> bool:
        key_hash = stable_hash(key)
        page_id = self._dir[key_hash & self._mask()]
        while page_id != NIL:
            page = self._read_bucket(page_id)
            if page.remove(key_hash, rid):
                self._write_bucket(page_id, page)
                self._consolidate(page_id, page)
                return True
            page_id = page.overflow_page_id
        return False

    def is_empty(self) -> bool:
        return all(not page.entries for _, page in self._iter_pages())

    # -------------------------------------------------------------- insertion

    def _insert_hash(self, key_hash: int, rid: RID) -> None:
        while True:
            idx = key_hash & self._mask()
            page_id = self._dir[idx]
            bucket = self._read_bucket(page_id)

            if len(bucket.entries) < self._capacity:
                bucket.add(key_hash, rid)
                self._write_bucket(page_id, bucket)
                return

            if self._is_stuck(bucket, key_hash):
                self._add_to_overflow(page_id, bucket, key_hash, rid)
                return

            if bucket.local_depth == self._global_depth:
                self._double_directory()
            self._split_bucket(idx, page_id, bucket)
            # the mask changed: the next turn recomputes the target bucket

    def _is_stuck(self, bucket: BucketPage, key_hash: int) -> bool:
        if bucket.local_depth >= HASH_BITS:
            return True
        bit = 1 << bucket.local_depth
        side = key_hash & bit
        return sum(1 for h, _ in bucket.entries if h & bit == side) >= self._capacity

    def _split_bucket(self, idx: int, page_id: int, bucket: BucketPage) -> None:
        old_depth = bucket.local_depth
        discriminating_bit = 1 << old_depth

        # the whole chain splits, not just the primary, or a chained bucket
        # freezes forever
        entries: list[tuple[int, RID]] = []
        spare: list[int] = []
        page = bucket
        while True:
            entries.extend(page.entries)
            next_id = page.overflow_page_id
            if next_id == NIL:
                break
            spare.append(next_id)
            page = self._read_bucket(next_id)

        keep: list[tuple[int, RID]] = []
        move: list[tuple[int, RID]] = []
        for h, rid in entries:
            (move if h & discriminating_bit else keep).append((h, rid))

        # the old primary is reused as the half that stays
        image_page_id = spare.pop() if spare else self._alloc_page()
        self._write_chain(page_id, keep, old_depth + 1, spare)
        self._write_chain(image_page_id, move, old_depth + 1, spare)
        for leftover in spare:
            self._free_page(leftover)

        # slots pointing here sit at stride 2**old_depth; one write per page
        low_bits = idx & (discriminating_bit - 1)
        touched: set[int] = set()
        for i in range(low_bits, len(self._dir), discriminating_bit):
            if i & discriminating_bit:
                self._dir[i] = image_page_id
                touched.add(i // ENTRIES_PER_DIR_PAGE)
        for k in sorted(touched):
            self._write_dir_page(k)

    def _write_chain(
        self,
        head_id: int,
        entries: list[tuple[int, RID]],
        local_depth: int,
        spare: list[int],
    ) -> None:
        cap = self._capacity
        # `or [[]]` so an empty side still gets its primary page
        chunks = [entries[i:i + cap] for i in range(0, len(entries), cap)] or [[]]

        page_ids = [head_id]
        while len(page_ids) < len(chunks):
            page_ids.append(spare.pop() if spare else self._alloc_page())

        for n, (pid, chunk) in enumerate(zip(page_ids, chunks)):
            page = BucketPage(
                local_depth=local_depth if n == 0 else 0,
                page_kind=PAGE_KIND_PRIMARY if n == 0 else PAGE_KIND_OVERFLOW,
            )
            page.entries = chunk
            page.overflow_page_id = page_ids[n + 1] if n + 1 < len(page_ids) else NIL
            self._write_bucket(pid, page)

    def _double_directory(self) -> None:
        # last-d-bits scheme: doubling is concatenation
        self._dir = self._dir + self._dir
        self._global_depth += 1
        self._grow_dir_pages()
        self._flush_dir_pages()
        self._flush_meta()

    def _add_to_overflow(
        self, primary_id: int, primary: BucketPage, key_hash: int, rid: RID
    ) -> None:
        first_id = primary.overflow_page_id

        if first_id != NIL:
            first = self._read_bucket(first_id)
            if len(first.entries) < self._capacity:
                first.add(key_hash, rid)
                self._write_bucket(first_id, first)
                return

        new_page = BucketPage(page_kind=PAGE_KIND_OVERFLOW)
        new_page.add(key_hash, rid)
        new_page.overflow_page_id = first_id
        new_id = self._alloc_page()
        # written before the primary points at it: a crash leaves an orphan
        # page rather than a dangling pointer
        self._write_bucket(new_id, new_page)
        primary.overflow_page_id = new_id
        self._write_bucket(primary_id, primary)

    def _consolidate(self, page_id: int, page: BucketPage) -> None:
        next_id = page.overflow_page_id
        if next_id == NIL:
            return
        next_page = self._read_bucket(next_id)
        if len(page.entries) + len(next_page.entries) > self._capacity:
            return
        page.entries.extend(next_page.entries)
        page.overflow_page_id = next_page.overflow_page_id
        self._write_bucket(page_id, page)
        self._free_page(next_id)

    # ------------------------------------------------------------ maintenance

    def bulk_load(self, pairs) -> None:
        pool, path = self._seg.pool, self._seg.path
        tmp_path = path + ".rebuild"
        # a leftover from an interrupted load would be opened instead of created
        pool.truncate(tmp_path, 0)
        fresh = ExtendibleHash(pool, tmp_path, bucket_capacity=self._capacity)
        for key, rid in pairs:
            fresh.insert(key, rid)
        pool.replace(tmp_path, path)
        self._load()

    # ----------------------------------------------------------------- paging

    def _mask(self) -> int:
        return (1 << self._global_depth) - 1

    def _alloc_page(self) -> int:
        reused = self._seg.free_head != NIL
        page_id = self._seg.alloc()
        if reused:
            self._flush_meta()
        return page_id

    def _free_page(self, page_id: int) -> None:
        # truncating instead of chaining would shift later page ids
        self._seg.free(page_id)
        self._flush_meta()

    def _read_bucket(self, page_id: int) -> BucketPage:
        return BucketPage.from_bytes(self._seg.read(page_id))

    def _write_bucket(self, page_id: int, page: BucketPage) -> None:
        self._seg.write(page_id, page.to_bytes())

    # --------------------------------------------------------------- metapage

    def _flush_meta(self) -> None:
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(
            META_FORMAT, buf, 0,
            self._global_depth, 0,
            self._capacity, 0,
            self._dir_pages[0], self._seg.free_head,
        )
        self._seg.write(META_PAGE, bytes(buf))

    def _create(self, bucket_capacity: int) -> None:
        self._global_depth = 0
        self._capacity = bucket_capacity

        self._seg.append(bytes(PAGE_SIZE))                    # page 0: metapage
        self._dir_pages = [self._seg.append(bytes(PAGE_SIZE))]  # page 1: directory
        first_bucket = self._seg.append(BucketPage().to_bytes())
        self._dir = [first_bucket]

        self._flush_dir_pages()
        self._flush_meta()

    def _load(self) -> None:
        global_depth, _flags, capacity, _pad, first_dir_page, free_head = (
            struct.unpack_from(META_FORMAT, self._seg.read(META_PAGE), 0)
        )

        self._global_depth = global_depth
        self._capacity = capacity
        self._seg.free_head = free_head
        self._load_dir(first_dir_page)

    def reload(self) -> None:
        self._load()

    # -------------------------------------------------------------- directory

    def _load_dir(self, first_dir_page: int) -> None:
        self._dir_pages = []
        self._dir = []
        page_id = first_dir_page
        while page_id != NIL:
            data = self._seg.read(page_id)
            self._dir_pages.append(page_id)
            self._dir.extend(
                struct.unpack_from(f"<{ENTRIES_PER_DIR_PAGE}i", data, DIR_HEADER_SIZE)
            )
            page_id = struct.unpack_from(DIR_HEADER_FORMAT, data, 0)[0]
        del self._dir[1 << self._global_depth:]  # drop the padding of the last page

    def _grow_dir_pages(self) -> None:
        needed = -(-len(self._dir) // ENTRIES_PER_DIR_PAGE)  # ceil
        while len(self._dir_pages) < needed:
            self._dir_pages.append(self._alloc_page())

    def _write_dir_page(self, k: int) -> None:
        start = k * ENTRIES_PER_DIR_PAGE
        chunk = self._dir[start:start + ENTRIES_PER_DIR_PAGE]
        next_page = self._dir_pages[k + 1] if k + 1 < len(self._dir_pages) else NIL

        buf = bytearray(PAGE_SIZE)
        struct.pack_into(DIR_HEADER_FORMAT, buf, 0, next_page)
        # tail beyond 2**D stays NIL so a reload can tell padding from a bucket
        padded = chunk + [NIL] * (ENTRIES_PER_DIR_PAGE - len(chunk))
        struct.pack_into(f"<{ENTRIES_PER_DIR_PAGE}i", buf, DIR_HEADER_SIZE, *padded)
        self._seg.write(self._dir_pages[k], bytes(buf))

    def _flush_dir_pages(self) -> None:
        for k in range(len(self._dir_pages)):
            self._write_dir_page(k)

    def _iter_pages(self):
        for page_id in dict.fromkeys(self._dir):  # dedup, keep order
            while page_id != NIL:
                page = self._read_bucket(page_id)
                yield page_id, page
                page_id = page.overflow_page_id
