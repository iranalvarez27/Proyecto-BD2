from dataclasses import dataclass, field
from common.types import Schema

STORAGE_HEAP = "heap"
STORAGE_SEQUENTIAL = "sequential"

INDEX_BPLUS = "bplus"
INDEX_HASH = "hash"
INDEX_CLUSTERED = "clustered"

@dataclass
class TableInfo:
    nombre: str
    schema: Schema
    storage: object
    tipo_storage: str
    key_column: str
    indices: dict = field(default_factory=dict)


class Catalog:
    def __init__(self):
        self._tablas: dict[str, TableInfo] = {}

    def register_table(self,nombre: str,schema: Schema,storage: object,tipo_storage: str,key_column: str,) -> None:
        if nombre in self._tablas:
            raise ValueError(f"la tabla '{nombre}' ya esta registrada")
        if tipo_storage not in (STORAGE_HEAP, STORAGE_SEQUENTIAL):
            raise ValueError(f"tipo de storage invalido: '{tipo_storage}'")

        schema.column_index(key_column)
        self._tablas[nombre] = TableInfo(nombre=nombre, schema=schema,storage=storage,
        tipo_storage=tipo_storage,key_column=key_column,)

    def register_index(self,tabla: str,columna: str,indice: object,tipo_indice: str,) -> None:
        info = self.get_table(tabla)
        info.schema.column_index(columna)
        if tipo_indice not in (INDEX_BPLUS, INDEX_HASH, INDEX_CLUSTERED):
            raise ValueError(f"tipo de indice invalido: '{tipo_indice}'")
        info.indices[columna] = (indice, tipo_indice)

    def tiene_indice(self, tabla: str, columna: str) -> bool:
        info = self.get_table(tabla)
        if columna in info.indices:
            return True
        return False

    def get_indice(self, tabla: str, columna: str):
        info = self.get_table(tabla)
        entrada = info.indices.get(columna)
        if entrada is None:
            raise ValueError(f"la columna '{columna}' no tiene indice en '{tabla}'")
        return entrada

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