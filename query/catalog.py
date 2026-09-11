from dataclasses import dataclass
from common.types import Schema

STORAGE_HEAP = "heap"
STORAGE_SEQUENTIAL = "sequential"


@dataclass
class TableInfo:
    nombre: str
    schema: Schema
    storage: object
    tipo_storage: str
    key_column: str


class Catalog:
    def __init__(self):
        self._tablas: dict[str, TableInfo] = {}

    def register_table(
        self,
        nombre: str,
        schema: Schema,
        storage: object,
        tipo_storage: str,
        key_column: str,
    ) -> None:
        if nombre in self._tablas:
            raise ValueError(f"La tabla '{nombre}' ya esta registrada")
        if tipo_storage not in (STORAGE_HEAP, STORAGE_SEQUENTIAL):
            raise ValueError(f"Tipo de storage invalido: '{tipo_storage}'")

        schema.column_index(key_column)
        self._tablas[nombre] = TableInfo(nombre=nombre,schema=schema,storage=storage,
        tipo_storage=tipo_storage,key_column=key_column,)

    def existe_tabla(self, nombre: str) -> bool:
        if nombre in self._tablas:
            return True
        return False

    def get_table(self, nombre: str) -> TableInfo:
        info = self._tablas.get(nombre)
        if info is None:
            raise ValueError(f"La tabla '{nombre}' no existe")
        return info

    def listar_tablas(self) -> list[str]:
        return list(self._tablas.keys())