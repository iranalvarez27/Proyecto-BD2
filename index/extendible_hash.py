import os
import struct
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import RID
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

MAGIC = b"EHIX"
VERSION = 1
META_PAGE = 0
# magic | version | global_depth | flags | bucket_capacity | pad | first_dir_page | free_list_head
META_FORMAT = "<4sHBBHHii"

# Directory pages: a next-page link, then a run of bucket page ids.
DIR_HEADER_FORMAT = "<i"
DIR_HEADER_SIZE = struct.calcsize(DIR_HEADER_FORMAT)  # 4
ENTRIES_PER_DIR_PAGE = (PAGE_SIZE - DIR_HEADER_SIZE) // 4  # 1023

NIL = -1


class ExtendibleHash(Index):
    """Non-clustered hash index: lossy (hash + RID, not the key), no ranges."""

    def __init__(self, path: str, bucket_capacity: int = MAX_ENTRIES):
        self._path = path
        if os.path.exists(path) and os.path.getsize(path) >= PAGE_SIZE:
            self._load()
        else:
            if not 1 <= bucket_capacity <= MAX_ENTRIES:
                raise ValueError(f"bucket_capacity must be in [1, {MAX_ENTRIES}]")
            self._create(bucket_capacity)

    # ------------------------------------------------------------------ Index

    def insert(self, key: Any, rid: RID) -> None:
        self._insert_hash(stable_hash(key), rid)

    def search(self, key: Any) -> list[RID]:
        """Candidates, not matches: the caller must recheck against the row."""
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

    # -------------------------------------------------------------- insertion

    def _insert_hash(self, key_hash: int, rid: RID) -> None:
        while True:
            idx = key_hash & self._mask()
            page_id = self._dir[idx]
            bucket = self._read_bucket(page_id)

            # case 1: it fits
            if len(bucket.entries) < self._capacity:
                bucket.add(key_hash, rid)
                self._write_bucket(page_id, bucket)
                return

            # case 2: full, and splitting cannot help
            if self._is_stuck(bucket, key_hash):
                self._add_to_overflow(page_id, bucket, key_hash, rid)
                return

            # case 3: full, and splitting does help
            if bucket.local_depth == self._global_depth:
                self._double_directory()
            self._split_bucket(idx, page_id, bucket)
            # retry: the target bucket is recomputed from scratch

    def _is_stuck(self, bucket: BucketPage, key_hash: int) -> bool:
        """True if splitting would not make room for key_hash."""
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
        """Write `entries` at `head_id` plus overflow pages, reusing `spare`."""
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
        """Insert at the head of the chain."""
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
        """Pulls the next link up when it fits. At most one page per delete."""
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

    def rebuild(self) -> None:
        """Reload every entry into a fresh index, compacting it."""
        entries = [(h, rid) for _, page in self._iter_pages() for h, rid in page.entries]
        tmp_path = self._path + ".rebuild"
        fresh = ExtendibleHash(tmp_path, bucket_capacity=self._capacity)
        for key_hash, rid in entries:
            fresh._insert_hash(key_hash, rid)
        os.replace(tmp_path, self._path)
        self._load()

    # ----------------------------------------------------------------- paging

    def _mask(self) -> int:
        return (1 << self._global_depth) - 1

    def _page_count(self) -> int:
        return os.path.getsize(self._path) // PAGE_SIZE

    def _read_raw(self, page_id: int) -> bytes:
        with open(self._path, "rb") as f:
            f.seek(page_id * PAGE_SIZE)
            return f.read(PAGE_SIZE)

    def _write_raw(self, page_id: int, data: bytes) -> None:
        with open(self._path, "r+b") as f:
            f.seek(page_id * PAGE_SIZE)
            f.write(data)

    def _append_raw(self, data: bytes) -> int:
        page_id = self._page_count()
        with open(self._path, "ab") as f:
            f.write(data)
        return page_id

    def _alloc_page(self) -> int:
        """Pop the free list, or extend the file."""
        if self._free_list_head == NIL:
            return self._append_raw(bytes(PAGE_SIZE))
        page_id = self._free_list_head
        self._free_list_head = struct.unpack_from("<i", self._read_raw(page_id), 0)[0]
        self._flush_meta()
        return page_id

    def _free_page(self, page_id: int) -> None:
        """Freed pages go on the list: truncating would shift later page ids."""
        buf = bytearray(PAGE_SIZE)
        struct.pack_into("<i", buf, 0, self._free_list_head)
        self._write_raw(page_id, bytes(buf))
        self._free_list_head = page_id
        self._flush_meta()

    def _read_bucket(self, page_id: int) -> BucketPage:
        return BucketPage.from_bytes(self._read_raw(page_id))

    def _write_bucket(self, page_id: int, page: BucketPage) -> None:
        self._write_raw(page_id, page.to_bytes())

    # --------------------------------------------------------------- metapage

    def _flush_meta(self) -> None:
        buf = bytearray(PAGE_SIZE)
        struct.pack_into(
            META_FORMAT, buf, 0,
            MAGIC, VERSION, self._global_depth, 0,
            self._capacity, 0,
            self._dir_pages[0], self._free_list_head,
        )
        self._write_raw(META_PAGE, bytes(buf))

    def _create(self, bucket_capacity: int) -> None:
        open(self._path, "wb").close()
        self._global_depth = 0
        self._capacity = bucket_capacity
        self._free_list_head = NIL

        self._append_raw(bytes(PAGE_SIZE))                    # page 0: metapage
        self._dir_pages = [self._append_raw(bytes(PAGE_SIZE))]  # page 1: directory
        first_bucket = self._append_raw(BucketPage().to_bytes())
        self._dir = [first_bucket]

        self._flush_dir_pages()
        self._flush_meta()

    def _load(self) -> None:
        magic, version, global_depth, _flags, capacity, _pad, first_dir_page, free_head = (
            struct.unpack_from(META_FORMAT, self._read_raw(META_PAGE), 0)
        )
        if magic != MAGIC:
            raise ValueError(f"{self._path} is not an extendible hash index")
        if version != VERSION:
            raise ValueError(f"{self._path} has on-disk format v{version}, expected v{VERSION}")

        self._global_depth = global_depth
        self._capacity = capacity
        self._free_list_head = free_head
        self._load_dir(first_dir_page)

    # -------------------------------------------------------------- directory

    def _load_dir(self, first_dir_page: int) -> None:
        self._dir_pages = []
        self._dir = []
        page_id = first_dir_page
        while page_id != NIL:
            data = self._read_raw(page_id)
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
        self._write_raw(self._dir_pages[k], bytes(buf))

    def _flush_dir_pages(self) -> None:
        """Whole-directory write. Only on doubling, which happens O(D) times."""
        for k in range(len(self._dir_pages)):
            self._write_dir_page(k)

    def _iter_pages(self):
        """Every live page reachable from the directory, primaries first."""
        for page_id in dict.fromkeys(self._dir):  # dedup, keep order
            while page_id != NIL:
                page = self._read_bucket(page_id)
                yield page_id, page
                page_id = page.overflow_page_id
