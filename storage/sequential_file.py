import os
import sys
from dataclasses import dataclass
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.page import SlottedPage, PAGE_SIZE
from common.record import Record
from common.types import Schema

MAIN_FILE = 0
AUX_FILE = 1
ENTRY_HEADER_FORMAT = "<bii?"
ENTRY_HEADER_SIZE = struct.calcsize(ENTRY_HEADER_FORMAT)
META_FORMAT = "<biibiiiii"
META_SAVE_EVERY = 32


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


def _pack_pointer(pointer: FilePointer | None) -> tuple[int, int, int]:
    if pointer is None:
        return (-1, -1, -1)
    return (pointer.file_type, pointer.page_id, pointer.slot_id)


def _unpack_pointer(file_type: int, page_id: int, slot_id: int) -> FilePointer | None:
    if file_type == -1:
        return None
    return FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)


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
        self._page_counts = {
            MAIN_FILE: os.path.getsize(data_path) // PAGE_SIZE,
            AUX_FILE: os.path.getsize(aux_path) // PAGE_SIZE,
        }
        self._meta_path = os.path.splitext(data_path)[0] + ".meta.bin"
        self._head: FilePointer | None = None
        self._tail: FilePointer | None = None
        self._tail_key = None
        self._n_aux = 0
        self._n_live = 0
        self._n_deleted = 0
        self._page_cache: tuple[int, int, SlottedPage, bool] | None = None
        self._unsaved = 0
        self._dirty_path = os.path.splitext(data_path)[0] + ".dirty.bin"
        self._fps = {}
        self._open_handles()
        self._load_state()

    def _empty_files(self) -> bool:
        return self._page_counts[MAIN_FILE] == 0 and self._page_counts[AUX_FILE] == 0

    def _open_handles(self) -> None:
        self._fps = {
            MAIN_FILE: open(self._data_path, "r+b"),
            AUX_FILE: open(self._aux_path, "r+b"),
        }

    def _close_handles(self) -> None:
        for file_type in list(self._fps):
            fp = self._fps.pop(file_type)
            try:
                fp.flush()
                fp.close()
            except Exception:
                pass

    def close(self) -> None:
        if not self._fps:
            return
        self._save_state()
        self._close_handles()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _load_state(self) -> None:
        if self._empty_files():
            return
        if os.path.exists(self._dirty_path):
            self._recover_state()
            self._save_state()
            return
        if os.path.exists(self._meta_path) and os.path.getsize(self._meta_path) == struct.calcsize(META_FORMAT):
            with open(self._meta_path, "rb") as file:
                data = file.read()
            h_ft, h_pid, h_sid, t_ft, t_pid, t_sid, n_aux, n_live, n_deleted = struct.unpack(META_FORMAT, data)
            self._head = _unpack_pointer(h_ft, h_pid, h_sid)
            self._tail = _unpack_pointer(t_ft, t_pid, t_sid)
            self._n_aux = n_aux
            self._n_live = n_live
            self._n_deleted = n_deleted
            if self._tail is not None:
                self._tail_key = self._get_key(self._read_entry(self._tail))
            return
        self._recover_state()
        self._save_state()

    def _save_state(self) -> None:
        self._flush_page_cache()
        payload = struct.pack(
            META_FORMAT,
            *_pack_pointer(self._head),
            *_pack_pointer(self._tail),
            self._n_aux,
            self._n_live,
            self._n_deleted,
        )
        with open(self._meta_path, "wb") as file:
            file.write(payload)
        if os.path.exists(self._dirty_path):
            os.remove(self._dirty_path)
        self._unsaved = 0

    def _mark_dirty(self) -> None:
        self._unsaved += 1
        if self._unsaved == 1:
            open(self._dirty_path, "wb").close()
        if self._unsaved >= META_SAVE_EVERY:
            self._save_state()

    def _recover_state(self) -> None:
        self._n_live = 0
        self._n_deleted = 0
        self._n_aux = 0
        for file_type in (MAIN_FILE, AUX_FILE):
            for pointer, entry in self._iter_file_entries(file_type):
                if entry.deleted:
                    self._n_deleted += 1
                    continue
                self._n_live += 1
                if file_type == AUX_FILE:
                    self._n_aux += 1
        self._head = self._discover_head()
        self._tail = None
        self._tail_key = None
        current = self._head
        while current is not None:
            entry = self._read_entry(current)
            if not entry.deleted:
                self._tail = current
                self._tail_key = self._get_key(entry)
            current = entry.next_pointer

    def _get_path(self, file_type: int) -> str:
        if file_type == MAIN_FILE:
            return self._data_path
        if file_type == AUX_FILE:
            return self._aux_path
        raise ValueError(f"Invalid file type: {file_type}")

    def page_count(self, file_type: int) -> int:
        return self._page_counts[file_type]

    def _flush_page_cache(self) -> None:
        if self._page_cache is None:
            return
        file_type, page_id, page, dirty = self._page_cache
        if dirty:
            self._write_page_disk(file_type, page_id, page)
            self._page_cache = (file_type, page_id, page, False)

    def _write_page_disk(self, file_type: int, page_id: int, page: SlottedPage) -> None:
        fp = self._fps[file_type]
        fp.seek(page_id * PAGE_SIZE)
        fp.write(page.to_bytes())

    def _read_page_disk(self, file_type: int, page_id: int) -> SlottedPage:
        fp = self._fps[file_type]
        fp.seek(page_id * PAGE_SIZE)
        data = fp.read(PAGE_SIZE)
        return SlottedPage.from_bytes(data)

    def _cached_page(self, file_type: int, page_id: int) -> SlottedPage:
        if (
            self._page_cache is not None
            and self._page_cache[0] == file_type
            and self._page_cache[1] == page_id
        ):
            return self._page_cache[2]
        self._flush_page_cache()
        page = self._read_page_disk(file_type, page_id)
        self._page_cache = (file_type, page_id, page, False)
        return page

    def _mark_cache_dirty(self) -> None:
        if self._page_cache is None:
            return
        file_type, page_id, page, _ = self._page_cache
        self._page_cache = (file_type, page_id, page, True)

    def read_page(self, file_type: int, page_id: int) -> SlottedPage:
        if page_id < 0 or page_id >= self.page_count(file_type):
            raise ValueError(f"Invalid page ID: {page_id}")
        return self._cached_page(file_type, page_id)

    def write_page(self, file_type: int, page_id: int, page: SlottedPage) -> None:
        if page_id < 0 or page_id >= self.page_count(file_type):
            raise ValueError(f"Invalid page ID: {page_id}")
        self._flush_page_cache()
        self._write_page_disk(file_type, page_id, page)
        self._page_cache = (file_type, page_id, page, False)

    def append_page(self, file_type: int, page: SlottedPage) -> int:
        self._flush_page_cache()
        page_id = self.page_count(file_type)
        fp = self._fps[file_type]
        fp.seek(0, os.SEEK_END)
        fp.write(page.to_bytes())
        self._page_counts[file_type] = page_id + 1
        self._page_cache = (file_type, page_id, page, False)
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
        page = self._cached_page(file_type, page_id)
        try:
            slot_id = page.insert(data)
            self._mark_cache_dirty()
            return FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)
        except ValueError:
            page = SlottedPage()
            slot_id = page.insert(data)
            page_id = self.append_page(file_type, page)
            return FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)

    def _read_entry(self, pointer: FilePointer) -> SequentialEntry:
        page = self._cached_page(pointer.file_type, pointer.page_id)
        data = page.read(pointer.slot_id)
        if data == b"":
            raise ValueError("Pointer references an empty slot")
        return SequentialEntry.unpack(data, self._schema)

    def _write_entry(self, pointer: FilePointer, entry: SequentialEntry) -> None:
        page = self._cached_page(pointer.file_type, pointer.page_id)
        data = entry.pack(self._schema)
        page.update(pointer.slot_id, data)
        self._mark_cache_dirty()

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
                pointer = FilePointer(file_type=file_type, page_id=page_id, slot_id=slot_id)
                yield pointer, entry

    def _discover_head(self) -> FilePointer | None:
        head_pointer = None
        head_key = None
        for file_type in (MAIN_FILE, AUX_FILE):
            for pointer, entry in self._iter_file_entries(file_type):
                if entry.deleted:
                    continue
                key = self._get_key(entry)
                if head_key is None or key < head_key:
                    head_key = key
                    head_pointer = pointer
        return head_pointer

    def _find_head(self) -> FilePointer | None:
        return self._head

    def _page_key_range(self, page: SlottedPage):
        first_key = None
        last_key = None
        for slot_id in range(page.slot_count):
            data = page.read(slot_id)
            if data == b"":
                continue
            key = self._get_key(SequentialEntry.unpack(data, self._schema))
            if first_key is None:
                first_key = key
            last_key = key
        return first_key, last_key

    def _last_live_before(self, page: SlottedPage, page_id: int, key) -> FilePointer | None:
        best = None
        for slot_id in range(page.slot_count):
            data = page.read(slot_id)
            if data == b"":
                continue
            entry = SequentialEntry.unpack(data, self._schema)
            if entry.deleted:
                continue
            if self._get_key(entry) < key:
                best = FilePointer(file_type=MAIN_FILE, page_id=page_id, slot_id=slot_id)
        return best

    def _find_live_main_predecessor(self, key) -> FilePointer | None:
        left = 0
        right = self.page_count(MAIN_FILE) - 1
        best = None
        while left <= right:
            middle = (left + right) // 2
            page = self.read_page(MAIN_FILE, middle)
            first_key, last_key = self._page_key_range(page)
            if last_key is None:
                right = middle - 1
                continue
            if last_key < key:
                candidate = self._last_live_before(page, middle, key)
                if candidate is not None:
                    best = candidate
                left = middle + 1
            elif first_key >= key:
                right = middle - 1
            else:
                candidate = self._last_live_before(page, middle, key)
                if candidate is not None:
                    best = candidate
                break
        return best

    def _find_insert_position(self, new_key):
        previous_pointer = self._find_live_main_predecessor(new_key)
        if previous_pointer is None:
            current_pointer = self._head
        else:
            current_pointer = self._read_entry(previous_pointer).next_pointer
        while current_pointer is not None:
            current_entry = self._read_entry(current_pointer)
            if current_entry.deleted:
                current_pointer = current_entry.next_pointer
                continue
            if new_key < self._get_key(current_entry):
                break
            previous_pointer = current_pointer
            current_pointer = current_entry.next_pointer
        return previous_pointer, current_pointer

    def _duplicate_key(self, new_key) -> bool:
        if self._tail_key is not None:
            if new_key == self._tail_key:
                return True
            if new_key > self._tail_key:
                return False
        return self.search(new_key) is not None

    def _last_main_key(self):
        for page_id in range(
            self.page_count(MAIN_FILE) - 1,
            -1,
            -1
        ):
            page = self.read_page(
                MAIN_FILE,
                page_id
            )

            for slot_id in range(
                page.slot_count - 1,
                -1,
                -1
            ):
                data = page.read(slot_id)

                if data == b"":
                    continue

                entry = SequentialEntry.unpack(
                    data,
                    self._schema
                )

                return self._get_key(entry)

        return None

    def insert(self, record: Record) -> FilePointer:
        new_key = record.values[self._key_index]
        if self._key_is_pk and self._duplicate_key(new_key):
            raise ValueError(f"Key {new_key} already exists")
        if self._head is None:
            entry = SequentialEntry(
                record=record,
                next_pointer=None,
                deleted=False
            )

            pointer = self._append_entry(
                MAIN_FILE,
                entry
            )

            self._head = pointer
            self._tail = pointer
            self._tail_key = new_key
            self._n_live += 1
            self._mark_dirty()

            return pointer
        last_main_key = self._last_main_key()

        if (
            self._tail is not None
            and self._tail_key is not None
            and last_main_key is not None
            and new_key > last_main_key
        ):
            new_entry = SequentialEntry(
                record=record,
                next_pointer=None,
                deleted=False
            )
            new_pointer = self._append_entry(
                MAIN_FILE,
                new_entry
            )

            tail_entry = self._read_entry(
                self._tail
            )

            tail_entry.next_pointer = new_pointer

            self._write_entry(
                self._tail,
                tail_entry
            )

            self._tail = new_pointer
            self._tail_key = new_key

            self._n_live += 1

            self._mark_dirty()

            return new_pointer        
        previous_pointer, current_pointer = self._find_insert_position(new_key)
        new_entry = SequentialEntry(record=record, next_pointer=current_pointer, deleted=False)
        new_pointer = self._append_entry(AUX_FILE, new_entry)
        if previous_pointer is not None:
            previous_entry = self._read_entry(previous_pointer)
            previous_entry.next_pointer = new_pointer
            self._write_entry(previous_pointer, previous_entry)
        else:
            self._head = new_pointer
        if current_pointer is None:
            self._tail = new_pointer
            self._tail_key = new_key
        self._n_aux += 1
        self._n_live += 1
        self._mark_dirty()
        return new_pointer

    def scan(self):
        current_pointer = self._head
        while current_pointer is not None:
            entry = self._read_entry(current_pointer)
            if not entry.deleted:
                yield entry.record
            current_pointer = entry.next_pointer

    def _find_by_key(self, key):
        previous_pointer = None
        current_pointer = self._head
        while current_pointer is not None:
            current_entry = self._read_entry(current_pointer)
            current_key = self._get_key(current_entry)
            if current_key == key and not current_entry.deleted:
                return (previous_pointer, current_pointer, current_entry)
            if current_key > key and not current_entry.deleted:
                break
            if not current_entry.deleted:
                previous_pointer = current_pointer
            current_pointer = current_entry.next_pointer
        return None, None, None

    def _binary_search_in_page(self, page_id: int, key):
        page = self.read_page(MAIN_FILE, page_id)
        left = 0
        right = page.slot_count - 1
        while left <= right:
            middle = (left + right) // 2
            data = page.read(middle)
            if data == b"":
                right = middle - 1
                continue
            entry = SequentialEntry.unpack(data, self._schema)
            current_key = self._get_key(entry)
            if current_key == key:
                if not entry.deleted:
                    pointer = FilePointer(file_type=MAIN_FILE, page_id=page_id, slot_id=middle)
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
            page = self.read_page(MAIN_FILE, middle)
            first_key, last_key = self._page_key_range(page)
            if first_key is None:
                right = middle - 1
                continue
            if key < first_key:
                right = middle - 1
            elif key > last_key:
                left = middle + 1
            else:
                return self._binary_search_in_page(middle, key)
        return None, None

    def _search_aux(self, key):
        for pointer, entry in self._iter_file_entries(AUX_FILE):
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
        previous_pointer, current_pointer, current_entry = self._find_by_key(key)
        if current_pointer is None:
            return False
        next_pointer = current_entry.next_pointer
        current_entry.deleted = True
        self._write_entry(current_pointer, current_entry)
        if previous_pointer is not None:
            previous_entry = self._read_entry(previous_pointer)
            previous_entry.next_pointer = next_pointer
            self._write_entry(previous_pointer, previous_entry)
        else:
            self._head = next_pointer
        if current_pointer == self._tail:
            self._tail = previous_pointer
            self._tail_key = None if previous_pointer is None else self._get_key(self._read_entry(previous_pointer))
        if current_pointer.file_type == AUX_FILE:
            self._n_aux -= 1
        self._n_live -= 1
        self._n_deleted += 1
        self._mark_dirty()
        return True

    def wasted_ratio(self) -> float:
        total_bytes = 0
        wasted_bytes = 0

        for file_type in (MAIN_FILE, AUX_FILE):
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
        return self._n_aux

    def reorganize(self) -> None:
        records = list(self.scan())
        self._page_cache = None
        self._close_handles()
        open(self._data_path, "wb").close()
        open(self._aux_path, "wb").close()
        self._page_counts[MAIN_FILE] = 0
        self._page_counts[AUX_FILE] = 0
        self._open_handles()
        pointers = []
        for record in records:
            entry = SequentialEntry(record=record, next_pointer=None, deleted=False)
            pointer = self._append_entry(MAIN_FILE, entry)
            pointers.append(pointer)
        for i in range(len(pointers) - 1):
            pointer = pointers[i]
            entry = self._read_entry(pointer)
            entry.next_pointer = pointers[i + 1]
            self._write_entry(pointer, entry)
        self._head = pointers[0] if pointers else None
        self._tail = pointers[-1] if pointers else None
        self._tail_key = None if not records else records[-1].values[self._key_index]
        self._n_aux = 0
        self._n_live = len(pointers)
        self._n_deleted = 0
        self._save_state()

    def needs_reorganization(self, threshold: float = 0.30, max_aux_records: int = 100) -> bool:
        return self.wasted_ratio() > threshold or self._n_aux >= max_aux_records

