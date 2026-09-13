import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import Schema, Column, DataType, IndexType
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile


@dataclass
class IndexMeta:
    name: str
    type: str  # "BTREE", "HASH"
    column: str
    clustered: bool = False


@dataclass
class TableMeta:
    name: str
    storage_type: str  # "HEAP" | "SEQUENTIAL"
    schema: Schema
    key_column: Optional[str] = None
    data_path: str = ""
    aux_path: str = ""
    indexes: List[IndexMeta] = field(default_factory=list)


class Catalog:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._tables: Dict[str, TableMeta] = {}

    def register_table(
        self,
        name: str,
        storage_type: str,
        schema: Schema,
        key_column: Optional[str] = None,
        indexes: Optional[List[IndexMeta]] = None,
    ) -> TableMeta:
        storage_type = storage_type.upper()
        data_path = os.path.join(self.data_dir, f"{name}.bin")
        aux_path = os.path.join(self.data_dir, f"{name}_aux.bin") if storage_type == "SEQUENTIAL" else ""

        meta = TableMeta(
            name=name,
            storage_type=storage_type,
            schema=schema,
            key_column=key_column,
            data_path=data_path,
            aux_path=aux_path,
            indexes=indexes or [],
        )
        self._tables[name] = meta
        return meta

    def get_table(self, name: str) -> Optional[TableMeta]:
        return self._tables.get(name)

    def list_tables(self) -> List[TableMeta]:
        return list(self._tables.values())

    def get_heap_file(self, name: str) -> Optional[HeapFile]:
        table = self.get_table(name)
        if not table or table.storage_type != "HEAP":
            return None
        return HeapFile(table.data_path)

    def get_sequential_file(self, name: str) -> Optional[SequentialFile]:
        table = self.get_table(name)
        if not table or table.storage_type != "SEQUENTIAL":
            return None
        key_col = table.key_column or (table.schema.columns[0].name if table.schema.columns else "id")
        return SequentialFile(table.data_path, table.aux_path, table.schema, key_col)
