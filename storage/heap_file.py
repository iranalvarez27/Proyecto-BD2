import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import SlottedPage
from common.record import Record
from common.types import Schema, RID
from engine.buffer_pool import BufferPool
from engine.segment import Segment

class HeapFile:
    def __init__(self, pool: BufferPool, file_path: str):
        self._file_path = file_path
        self._seg = Segment(pool, file_path)
        self._reusable: set[int] = set()
        self._free_space: dict[int, int] = {}
        self._deleted_pages: set[int] = set()
        self._holes_scanned = False

    def page_count(self) -> int:
        return self._seg.page_count()

    def reload(self) -> None:
        self._reusable.clear()
        self._free_space.clear()
        self._deleted_pages.clear()
        self._holes_scanned = False

    def close(self) -> None:
        self._seg.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def read_page(self, page_id: int) -> SlottedPage:
        if page_id < 0 or page_id >= self.page_count():
            raise ValueError(f"Invalid page ID: {page_id}")
        return SlottedPage.from_bytes(self._seg.read(page_id))

    def write_page(self, page_id: int, page: SlottedPage) -> None:
        if page_id < 0 or page_id >= self.page_count():
            raise ValueError(f"Invalid page ID: {page_id}")
        self._seg.write(page_id, page.to_bytes())

    def append_page(self, page: SlottedPage) -> int:
        return self._seg.append(page.to_bytes())

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

        self.write_page(page_id, page)

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

        for page_id in range(self.page_count()):
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
        n = self.page_count()
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

        self.write_page(rid.page_id, page)

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
        for page_id in range(self.page_count()):
            page = self.read_page(page_id)
            for slot_id in range(page.slot_count):
                data = page.read(slot_id)
                if data == b"":
                    continue
                yield Record.unpack(data, schema)

    def scan_con_rid(self, schema: Schema):
        for page_id in range(self.page_count()):
            page = self.read_page(page_id)
            for slot_id in range(page.slot_count):
                data = page.read(slot_id)
                if data == b"":
                    continue
                yield RID(page_id=page_id, slot_id=slot_id), Record.unpack(data, schema)
