import os
from dataclasses import dataclass

from common.page import SlottedPage, PAGE_SIZE
from common.record import Record
from common.types import Schema

MAIN_FILE = 0
AUX_FILE = 1

@dataclass(frozen=True)
class FilePointer: 
    file_type: int
    page_id: int
    slot_id: int

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
            