import heapq
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.record import Record
from common.types import DataType
from engine.buffer_pool import BufferPool
from index.bplus_tree import BPlusTree, DuplicateKey
from storage.sequential_file import AUX_FILE, MAIN_FILE, SequentialEntry, SequentialFile

DELETED_LIMIT = 0.30


class ClusteredBPlusTree:
    """Clustered B+ tree over a SequentialFile's primary key."""

    def __init__(self, pool: BufferPool, seq: SequentialFile, index_path: str):
        self._seq = seq
        self._schema = seq._schema
        self._key_index = seq._key_index
        key_type = self._schema.columns[self._key_index].type

        fresh = pool.page_count(index_path) == 0
        self._tree = BPlusTree(pool, index_path, key_type, clustered=True)
        if fresh:
            self._rebuild()

    # ----------------------------------------------------------------- reads

    def search(self, key):
        """Two sources: the MAIN page the tree points at, then AUX."""
        page_id = self._tree.floor(key)
        if page_id is not None:
            for entry in self._live_in_page(page_id):
                if self._key_of(entry) == key:
                    return entry.record
        for entry in self._aux_rows():
            if self._key_of(entry) == key:
                return entry.record
        return None

    def range_search(self, low, high) -> list[Record]:
        """Inclusive [low, high]."""
        if low > high:
            return []
        start = self._tree.floor(low)
        from_main = []
        done = False
        for page_id in range(start or 0, self._seq.page_count(MAIN_FILE)):
            for entry in self._live_in_page(page_id):
                k = self._key_of(entry)
                if k > high:
                    done = True
                    break
                if k >= low:
                    from_main.append((k, entry.record))
            if done:
                break

        from_aux = sorted(
            (self._key_of(e), e.record)
            for e in self._aux_rows()
            if low <= self._key_of(e) <= high
        )
        return [r for _, r in heapq.merge(from_main, from_aux, key=lambda t: t[0])]

    # ---------------------------------------------------------------- writes

    def insert(self, record: Record):
        key = record.values[self._key_index]
        if self.search(key) is not None:
            raise DuplicateKey(key)
        rid = self._seq.insert(record)
        self._track(key, rid)
        return rid

    def delete(self, key):
        return self._seq.delete(key)

    def reorganize(self) -> None:
        self._seq.reorganize()
        self._rebuild()

    def reload(self) -> None:
        """After a ROLLBACK the tree's metapage was restored behind its back
        (the SequentialFile reloads itself, it is the table's storage)."""
        self._tree.reload()

    # --------------------------------------------------------------- policy

    def aux_limit(self) -> int:
        """AUX pages tolerated, bounded by what a binary search over MAIN costs."""
        return max(1, int(math.log2(max(self._seq.page_count(MAIN_FILE), 2))))

    def aux_pages(self) -> int:
        return self._seq.page_count(AUX_FILE)

    def needs_reorganization(self) -> bool:
        return (
            self.aux_pages() > self.aux_limit()
            or self._seq.deleted_ratio() > DELETED_LIMIT
        )

    # ------------------------------------------------------------- internals

    def _key_of(self, entry: SequentialEntry):
        return entry.record.values[self._key_index]

    def _track(self, key, rid) -> None:
        if rid.page_id < 0:   # AUX
            return
        if self._tree.floor(key) != rid.page_id:
            self._tree.insert(key, rid.page_id)

    def _live_in_page(self, page_id: int):
        page = self._seq.read_page(MAIN_FILE, page_id)
        for slot_id in range(page.slot_count):
            data = page.read(slot_id)
            if data == b"":
                continue
            entry = SequentialEntry.unpack(data, self._schema)
            if not entry.deleted:
                yield entry

    def _main_rows(self):
        for page_id in range(self._seq.page_count(MAIN_FILE)):
            yield from self._live_in_page(page_id)

    def _aux_rows(self):
        for _pointer, entry in self._seq._iter_file_entries(AUX_FILE):
            if not entry.deleted:
                yield entry

    def _page_minimums(self):
        for page_id in range(self._seq.page_count(MAIN_FILE)):
            keys = [self._key_of(e) for e in self._live_in_page(page_id)]
            if keys:
                yield min(keys), page_id

    def _rebuild(self) -> None:
        pairs = list(self._page_minimums())
        self._tree.bulk_load(pairs)
