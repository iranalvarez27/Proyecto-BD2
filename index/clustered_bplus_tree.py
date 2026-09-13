import heapq
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import PAGE_SIZE
from common.record import Record
from common.types import DataType
from index.bplus_tree import BPlusTree, DuplicateKey
from storage.sequential_file import AUX_FILE, MAIN_FILE, SequentialEntry, SequentialFile


class ClusteredBPlusTree:
    """Clustered B+ tree over a SequentialFile's primary key."""

    def __init__(self, seq: SequentialFile, index_path: str):
        self._seq = seq
        self._schema = seq._schema
        self._key_index = seq._key_index
        key_type = self._schema.columns[self._key_index].type

        fresh = not (os.path.exists(index_path) and os.path.getsize(index_path) >= PAGE_SIZE)
        self._tree = BPlusTree(index_path, key_type, clustered=True)
        self._n_main = 0
        if fresh:
            self._rebuild()
        else:
            self._n_main = sum(1 for _ in self._main_rows())

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
        """Inclusive [low, high]. MAIN pages are walked by consecutive page
        id, since logical and physical order match here."""
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

    def insert(self, record: Record) -> None:
        key = record.values[self._key_index]
        if self.search(key) is not None:
            raise DuplicateKey(key)
        before = self._main_extent()
        self._seq.insert(record)
        if self._main_extent() != before:
            self._rebuild()
        elif self.aux_count() > self.aux_limit():
            self.reorganize()

    def delete(self, key) -> bool:
        if not self._seq.delete(key):
            return False
        if self._seq.needs_reorganization():
            self.reorganize()
        return True

    def reorganize(self) -> None:
        self._seq.reorganize()
        self._rebuild()

    # --------------------------------------------------------------- policy

    def aux_limit(self) -> int:
        return max(1, int(math.log2(max(self._n_main, 2))))

    def aux_count(self) -> int:
        return sum(1 for _ in self._aux_rows())

    # ------------------------------------------------------------- internals

    def _key_of(self, entry: SequentialEntry):
        return entry.record.values[self._key_index]

    def _main_extent(self) -> tuple[int, int]:
        """Page count plus the last page's slot count: detects a write to
        MAIN using only the sequential file's public API."""
        pages = self._seq.page_count(MAIN_FILE)
        if pages == 0:
            return (0, 0)
        return (pages, self._seq.read_page(MAIN_FILE, pages - 1).slot_count)

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
        """(minimum, page_id) for every MAIN page that still has a live row."""
        for page_id in range(self._seq.page_count(MAIN_FILE)):
            keys = [self._key_of(e) for e in self._live_in_page(page_id)]
            if keys:
                yield min(keys), page_id

    def _rebuild(self) -> None:
        pairs = list(self._page_minimums())
        self._tree.bulk_load(pairs)
        self._n_main = sum(1 for _ in self._main_rows())
