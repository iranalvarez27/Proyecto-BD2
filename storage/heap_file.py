import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import SlottedPage, PAGE_SIZE
from common.record import Record
from common.types import Schema, RID


class HeapFile:
    def __init__(self, file_path: str):
        self._file_path = file_path
        if not os.path.exists(file_path):
            open(file_path, "wb").close()
        self._n_pages = os.path.getsize(file_path) // PAGE_SIZE
        self._reusable: set[int] = set()
        self._free_space: dict[int, int] = {}
        self._deleted_pages: set[int] = set()
        self._holes_scanned = False
        self._page_cache: tuple[int, SlottedPage, bool] | None = None
        self._fp = open(file_path, "r+b")

    def page_count(self) -> int:
        return self._n_pages

    def close(self) -> None:
        if self._fp is None:
            return
        self._flush_page_cache()
        self._fp.flush()
        self._fp.close()
        self._fp = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _flush_page_cache(self) -> None:
        if self._page_cache is None or self._fp is None:
            return
        page_id, page, dirty = self._page_cache
        if dirty:
            self._write_page_disk(page_id, page)
            self._page_cache = (page_id, page, False)

    def _write_page_disk(self, page_id: int, page: SlottedPage) -> None:
        self._fp.seek(page_id * PAGE_SIZE)
        self._fp.write(page.to_bytes())

    def _read_page_disk(self, page_id: int) -> SlottedPage:
        self._fp.seek(page_id * PAGE_SIZE)
        data = self._fp.read(PAGE_SIZE)
        return SlottedPage.from_bytes(data)

    def read_page(self, page_id: int) -> SlottedPage:
        if page_id < 0 or page_id >= self._n_pages:
            raise ValueError(f"Invalid page ID: {page_id}")
        if self._page_cache is not None and self._page_cache[0] == page_id:
            return self._page_cache[1]
        self._flush_page_cache()
        page = self._read_page_disk(page_id)
        self._page_cache = (page_id, page, False)
        return page

    def write_page(self, page_id: int, page: SlottedPage) -> None:
        if page_id < 0 or page_id >= self._n_pages:
            raise ValueError(f"Invalid page ID: {page_id}")
        self._flush_page_cache()
        self._write_page_disk(
            page_id,
            page
        )
        self._page_cache = (
            page_id,
            page,
            False
        )

    def append_page(self, page: SlottedPage) -> int:
        self._flush_page_cache()
        page_id = self._n_pages
        self._fp.seek(0, os.SEEK_END)
        self._fp.write(page.to_bytes())
        self._n_pages = page_id + 1
        self._page_cache = (page_id, page, False)
        return page_id

    def _try_insert(
        self,
        page_id: int,
        data: bytes
    ) -> RID | None:

        page = self.read_page(page_id)

        try:
            slot_id = page.insert(data)

        except ValueError:

            free = page.free_space()

            self._free_space[page_id] = free

            if page_id in self._deleted_pages:

                still_has_deleted = False

                for slot_id in range(page.slot_count):
                    if page.read(slot_id) == b"":
                        still_has_deleted = True
                        break

                if not still_has_deleted:
                    self._deleted_pages.discard(
                        page_id
                    )

            if (
                free <= 0
                and page_id not in self._deleted_pages
            ):
                self._reusable.discard(
                    page_id
                )

            return None

        self._page_cache = (
            page_id,
            page,
            True
        )

        free = page.free_space()

        self._free_space[page_id] = free

        if (
            free > 0
            or page_id in self._deleted_pages
        ):
            self._reusable.add(page_id)
        else:
            self._reusable.discard(page_id)

        return RID(
            page_id=page_id,
            slot_id=slot_id
        )
    def _discover_reusable_pages(self) -> None:
        if self._holes_scanned:
            return

        for page_id in range(self._n_pages):
            page = self.read_page(page_id)

            free = page.free_space()

            self._free_space[page_id] = free

            has_deleted_slot = False

            for slot_id in range(page.slot_count):
                if page.read(slot_id) == b"":
                    has_deleted_slot = True
                    break

            if has_deleted_slot:
                self._deleted_pages.add(page_id)

            if (
                free > 0
                or has_deleted_slot
            ):
                self._reusable.add(page_id)

        self._holes_scanned = True
    def _candidate_pages(
        self,
        data_size: int,
        last_page: int
    ) -> list[int]:

        candidates = []

        for page_id in self._reusable:

            if page_id == last_page:
                continue

            free = self._free_space.get(
                page_id,
                0
            )

            if free >= data_size:
                candidates.append(page_id)

            elif page_id in self._deleted_pages:
                candidates.append(page_id)

        candidates.sort(
            key=lambda page_id: self._free_space.get(
                page_id,
                0
            ),
            reverse=True
        )

        return candidates

    def insert(self, record: Record, schema: Schema) -> RID:
        data = record.pack(schema)
        n = self._n_pages
        if n > 0:
            rid = self._try_insert(
                n - 1,
                data
            )

            if rid is not None:
                return rid
        if self._reusable:
            candidates = self._candidate_pages(
                len(data),
                n - 1
            )

            for page_id in candidates:
                rid = self._try_insert(
                    page_id,
                    data
                )

                if rid is not None:
                    return rid
        if (
            not self._holes_scanned
            and n > 1
        ):
            self._discover_reusable_pages()

            candidates = self._candidate_pages(
                len(data),
                n - 1
            )

            for page_id in candidates:
                rid = self._try_insert(
                    page_id,
                    data
                )

                if rid is not None:
                    return rid

        page = SlottedPage()

        slot_id = page.insert(data)

        page_id = self.append_page(
            page
        )

        self._free_space[page_id] = page.free_space()

        if page.free_space() > 0:
            self._reusable.add(page_id)

        return RID(
            page_id=page_id,
            slot_id=slot_id
        )
    def read(self, rid: RID, schema: Schema) -> Record | None:
        page = self.read_page(rid.page_id)
        data = page.read(rid.slot_id)
        if data == b"":
            return None
        return Record.unpack(data, schema)

    def delete(self, rid: RID) -> None:
        page = self.read_page(
            rid.page_id
        )

        page.delete(
            rid.slot_id
        )

        self._page_cache = (
            rid.page_id,
            page,
            True
        )

        self._deleted_pages.add(
            rid.page_id
        )

        self._free_space[
            rid.page_id
        ] = page.free_space()

        self._reusable.add(
            rid.page_id
        )

    def scan(self, schema: Schema):
        for page_id in range(self._n_pages):
            page = self.read_page(page_id)
            for slot_id in range(page.slot_count):
                data = page.read(slot_id)
                if data == b"":
                    continue
                yield Record.unpack(data, schema)

    def scan_con_rid(self, schema: Schema):
        for page_id in range(self._n_pages):
            page = self.read_page(page_id)
            for slot_id in range(page.slot_count):
                data = page.read(slot_id)
                if data == b"":
                    continue
                yield RID(page_id=page_id, slot_id=slot_id), Record.unpack(data, schema)
