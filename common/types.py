from dataclasses import dataclass, field
from enum import Enum

class DataType(Enum):
    INT = "INT"
    SMALLINT = "SMALLINT"
    BIGINT = "BIGINT"
    FLOAT = "FLOAT"
    DOUBLE = "DOUBLE"
    BOOL = "BOOL"
    CHAR = "CHAR"
    VARCHAR = "VARCHAR"
    POINT = "POINT"

class IndexType(Enum):
    BTREE = "BTREE"
    HASH = "HASH"

@dataclass
class Column:
    name: str
    type: DataType
    size: int
    is_pk: bool = False

@dataclass
class Schema:
    table_name: str
    columns: list[Column] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        for i, col in enumerate(self.columns):
            if col.name == name:
                return i
        raise ValueError(f"Column '{name}' does not exist in '{self.table_name}'")
    
@dataclass(frozen=True)
class RID:
    page_id: int
    slot_id: int
