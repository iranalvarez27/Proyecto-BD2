import os
import sys
from dataclasses import dataclass
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import SlottedPage, PAGE_SIZE
from common.record import Record
from common.types import Schema
from transaction import manager as tx_manager

MAIN_FILE = 0
AUX_FILE = 1
ENTRY_HEADER_FORMAT = "<bii?"
ENTRY_HEADER_SIZE = struct.calcsize(ENTRY_HEADER_FORMAT)


@dataclass(frozen=True)
class FilePointer:
    file_type: int
    page_id: int
    slot_id: int


@dataclass
class SequentialEntry:
    record: Record
    next_pointer: FilePointer | None = None
    deleted: bool = False

    def pack(self, schema: Schema) -> bytes:
        if self.next_pointer is None:
            file_type = -1
            page_id = -1
            slot_id = -1
        else:
            file_type = self.next_pointer.file_type
            page_id = self.next_pointer.page_id
            slot_id = self.next_pointer.slot_id
        header = struct.pack(ENTRY_HEADER_FORMAT, file_type, page_id, slot_id, self.deleted)
        return header + self.record.pack(schema)

    @classmethod
    def unpack(cls, data: bytes, schema: Schema) -> "SequentialEntry":
        file_type, page_id, slot_id, deleted = struct.unpack_from(ENTRY_HEADER_FORMAT, data, 0)
        if file_type == -1:
            next_pointer = None
        else:
            next_pointer = FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)
        record_data = data[ENTRY_HEADER_SIZE:]
        record = Record.unpack(record_data, schema)
        return cls(record=record, next_pointer=next_pointer, deleted=deleted)

class SequentialFile:
    def __init__(self, data_path: str, aux_path: str, schema: Schema, key_column: str):
        self._data_path = data_path
        self._aux_path = aux_path
        self._schema = schema
        self._key_column = key_column
        self._key_index = schema.column_index(key_column)
        self._key_is_pk = schema.columns[self._key_index].is_pk
        if not os.path.exists(data_path):
            open(data_path, "wb").close()
        if not os.path.exists(aux_path):
            open(aux_path, "wb").close()
    def _get_path(self, file_type: int) -> str:
        if file_type == MAIN_FILE:
                return self._data_path
        if file_type == AUX_FILE:
                return self._aux_path
        raise ValueError(f"Invalid file type: {file_type}")
    def page_count(self, file_type: int) -> int:
        path = self._get_path(file_type)
        file_size = os.path.getsize(path)
        return file_size // PAGE_SIZE
    def read_page(self, file_type: int, page_id: int) -> SlottedPage:
        path = self._get_path(file_type)
        if page_id < 0 or page_id >= self.page_count(file_type):
            raise ValueError(f"Invalid page ID: {page_id}")
        with open(path, "rb") as file:
            file.seek(page_id * PAGE_SIZE)
            data = file.read(PAGE_SIZE)
        return SlottedPage.from_bytes(data)
    def write_page(self, file_type: int, page_id: int, page: SlottedPage) -> None:
        path = self._get_path(file_type)
        if page_id < 0 or page_id >= self.page_count(file_type):
            raise ValueError(f"Invalid page ID: {page_id}")
        with open(path, "r+b") as file:
            file.seek(page_id * PAGE_SIZE)
            before = file.read(PAGE_SIZE)
            tx_manager.TX_HOOK("WRITE", path, page_id, before)
            file.seek(page_id * PAGE_SIZE)
            file.write(page.to_bytes())
    def append_page(self, file_type: int, page: SlottedPage) -> int:
        path = self._get_path(file_type)
        page_id = self.page_count(file_type)
        tx_manager.TX_HOOK("APPEND", path, page_id, None)
        with open(path, "ab") as file:
            file.write(page.to_bytes())
        return page_id
    def _append_entry(self, file_type: int, entry: SequentialEntry) -> FilePointer:
        data = entry.pack(self._schema)
        page_count = self.page_count(file_type)
        if page_count == 0:
            page = SlottedPage()
            slot_id = page.insert(data)
            page_id = self.append_page(file_type, page)
            return FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)
        page_id = page_count - 1
        page = self.read_page(file_type, page_id)
        try: 
            slot_id = page.insert(data)
            self.write_page(file_type, page_id, page)
            return FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)
        except ValueError: 
            page = SlottedPage()
            slot_id = page.insert(data)
            page_id = self.append_page(file_type, page)
            return FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)
    def _read_entry(self, pointer: FilePointer) -> SequentialEntry:
        page = self.read_page(pointer.file_type, pointer.page_id)
        data = page.read(pointer.slot_id)
        if data == b"":
            raise ValueError(f"Pointer references an empty slot")
        return SequentialEntry.unpack(data, self._schema)
    def _write_entry(self, pointer: FilePointer, entry: SequentialEntry) -> None:
        page = self.read_page(pointer.file_type, pointer.page_id)
        data = entry.pack(self._schema)
        page.update(pointer.slot_id, data)
        self.write_page(pointer.file_type, pointer.page_id, page)
    def _get_key(self, entry: SequentialEntry):
        return entry.record.values[self._key_index]
    def _iter_file_entries(self, file_type: int):
        for page_id in range(self.page_count(file_type)):
            page = self.read_page(file_type, page_id)
            for slot_id in range(page.slot_count):
                data = page.read(slot_id)
                if data == b"":
                    continue
                entry = SequentialEntry.unpack(data, self._schema)
                pointer = FilePointer(file_type=file_type,
                    page_id=page_id,
                    slot_id=slot_id
                )

                yield pointer, entry
    def _find_head(self) -> FilePointer | None:
        head_pointer = None
        head_key = None
        for file_type in [MAIN_FILE, AUX_FILE]:
            for pointer, entry in self._iter_file_entries(file_type):
                if entry.deleted:
                    continue
                key = self._get_key(entry)
                if head_key is None or key < head_key:
                    head_key = key
                    head_pointer = pointer
        return head_pointer
    def insert(self, record: Record) -> FilePointer:
        new_key = record.values[self._key_index]
        if self._key_is_pk and self.search(new_key) is not None:
            raise ValueError(f"Key {new_key} already exists")
        head = self._find_head()
        if head is None:
            entry = SequentialEntry(record=record, next_pointer=None, deleted=False)
            return self._append_entry(MAIN_FILE, entry)
        previous_pointer = None
        current_pointer = head
        while current_pointer is not None:
            current_entry = self._read_entry(current_pointer)
            current_key = self._get_key(current_entry)
            if new_key < current_key:
                break
            previous_pointer = current_pointer
            current_pointer = current_entry.next_pointer
        new_entry = SequentialEntry(record=record, next_pointer=current_pointer, deleted=False)
        new_pointer = self._append_entry(AUX_FILE, new_entry)
        if previous_pointer is not None:
            previous_entry = self._read_entry(previous_pointer)
            previous_entry.next_pointer = new_pointer
            self._write_entry(previous_pointer, previous_entry)
        return new_pointer
    def scan(self):
        current_pointer = self._find_head()

        while current_pointer is not None:
            entry = self._read_entry(
                current_pointer
            )

            if not entry.deleted:
                yield entry.record

            current_pointer = entry.next_pointer
    def _find_by_key(self, key):
        previous_pointer = None
        current_pointer = self._find_head()
        while current_pointer is not None:
            current_entry = self._read_entry(current_pointer)
            current_key = self._get_key(current_entry)
            if current_key == key and not current_entry.deleted:
                return (previous_pointer, current_pointer, current_entry)
            if current_key > key:
                break
            previous_pointer = current_pointer
            current_pointer = current_entry.next_pointer
        return None, None, None
    def _binary_search_in_page(
        self,
        page_id: int,
        key
    ):
        page = self.read_page(
            MAIN_FILE,
            page_id
        )

        left = 0
        right = page.slot_count - 1

        while left <= right:
            middle = (left + right) // 2

            data = page.read(middle)

            entry = SequentialEntry.unpack(
                data,
                self._schema
            )

            current_key = self._get_key(entry)

            if current_key == key:
                if not entry.deleted:
                    pointer = FilePointer(
                        file_type=MAIN_FILE,
                        page_id=page_id,
                        slot_id=middle
                    )

                    return pointer, entry

                return None, None

            if key < current_key:
                right = middle - 1
            else:
                left = middle + 1

        return None, None
    def _search_main_binary(self, key):
        left = 0
        right = self.page_count(MAIN_FILE) - 1

        while left <= right:
            middle = (left + right) // 2

            page = self.read_page(
                MAIN_FILE,
                middle
            )

            if page.slot_count == 0:
                return None, None

            first_data = page.read(0)
            last_data = page.read(
                page.slot_count - 1
            )

            first_entry = SequentialEntry.unpack(
                first_data,
                self._schema
            )

            last_entry = SequentialEntry.unpack(
                last_data,
                self._schema
            )

            first_key = self._get_key(first_entry)
            last_key = self._get_key(last_entry)

            if key < first_key:
                right = middle - 1

            elif key > last_key:
                left = middle + 1

            else:
                return self._binary_search_in_page(
                    middle,
                    key
                )

        return None, None   
    def _search_aux(self, key):
        for pointer, entry in self._iter_file_entries(
            AUX_FILE
        ):
            if entry.deleted:
                continue

            if self._get_key(entry) == key:
                return pointer, entry

        return None, None 
    def search(self, key) -> Record | None:
        _, entry = self._search_main_binary(key)
        if entry is not None:
            return entry.record
        _, entry = self._search_aux(key)
        if entry is not None:
            return entry.record
        return None
    def delete(self, key) -> bool:
        previous_pointer, current_pointer, current_entry = \
            self._find_by_key(key)
        if current_pointer is None:
            return False
        next_pointer = current_entry.next_pointer
        current_entry.deleted = True
        self._write_entry(
            current_pointer,
            current_entry
        )
        if previous_pointer is not None:
            previous_entry = self._read_entry(
                previous_pointer
            )

            previous_entry.next_pointer = next_pointer

            self._write_entry(
                previous_pointer,
                previous_entry
            )

        return True
    def wasted_ratio(self) -> float:
        total_bytes = 0
        wasted_bytes = 0
        for file_type in [MAIN_FILE, AUX_FILE]:
            for page_id in range(self.page_count(file_type)):
                page = self.read_page(
                    file_type,
                    page_id
                )
                for slot_id in range(page.slot_count):
                    data = page.read(slot_id)
                    if data == b"":
                        continue
                    total_bytes += len(data)
                    entry = SequentialEntry.unpack(
                        data,
                        self._schema
                    )
                    if entry.deleted:
                        wasted_bytes += len(data)
        if total_bytes == 0:
            return 0.0
        return wasted_bytes / total_bytes
    def aux_record_count(self) -> int:
        count = 0

        for _, entry in self._iter_file_entries(AUX_FILE):
            if not entry.deleted:
                count += 1

        return count
    def reorganize(self) -> None:
        records = list(self.scan())

        with open(self._data_path, "rb") as f:
            snapshot_main = f.read()
        with open(self._aux_path, "rb") as f:
            snapshot_aux = f.read()
        tx_manager.TX_HOOK("SNAPSHOT", self._data_path, None, snapshot_main)
        tx_manager.TX_HOOK("SNAPSHOT", self._aux_path, None, snapshot_aux)

        open(
            self._data_path,
            "wb"
        ).close()
        open(
            self._aux_path,
            "wb"
        ).close()
        pointers = []
        for record in records:
            entry = SequentialEntry(
                record=record,
                next_pointer=None,
                deleted=False
            )
            pointer = self._append_entry(
                MAIN_FILE,
                entry
            )
            pointers.append(pointer)
        for i in range(len(pointers) - 1):
            pointer = pointers[i]

            entry = self._read_entry(
                pointer
            )

            entry.next_pointer = pointers[i + 1]

            self._write_entry(
                pointer,
                entry
            )
    def needs_reorganization(self, threshold: float = 0.30, max_aux_records: int = 100) -> bool:
        too_much_waste = self.wasted_ratio() > threshold
        aux_too_large = (self.aux_record_count() >= max_aux_records)
        return too_much_waste or aux_too_large

