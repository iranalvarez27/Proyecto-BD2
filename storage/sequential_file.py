import os
from dataclasses import dataclass
import struct

from common.page import SlottedPage, PAGE_SIZE
from common.record import Record
from common.types import Schema

MAIN_FILE = 0
AUX_FILE = 1
ENTRY_HEADER_FORMAT = "<bii?"
ENTRY_HEADER_SIZE = struct.calcsize(ENTRY_HEADER_FORMAT)

@dataclass 
class SequentialEntry:
    record: Record
    next_pointer: FilePointer | None = None
    deleted: bool = False
    def pack(self, schema: Schema) -> bytes:
        if self.next_pointer is None:
            file_type = 0
            page_id = 0
            slot_id = 0
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
        if not os.path.exists(data_path):
            open(data_path, "wb").close()
        if not os.path.exists(aux_path):
            open(aux_path, "wb").close()
    