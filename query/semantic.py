from query.ast import (
    SelectNode, InsertNode, DeleteNode, Condition, BinaryCondition, OrderBy,
    BeginNode, CommitNode, RollbackNode,
)
from query.catalog import Catalog
from common.types import Schema, DataType


class SemanticError(Exception):
    pass


class SemanticAnalyzer:
    def __init__(self, catalog: Catalog):
        self._catalog = catalog

    def validar(self, nodo) -> None:
        if isinstance(nodo, SelectNode):
            self.validar_select(nodo)
        elif isinstance(nodo, InsertNode):
            self.validar_insert(nodo)
        elif isinstance(nodo, DeleteNode):
            self.validar_delete(nodo)
        elif isinstance(nodo, (BeginNode, CommitNode, RollbackNode)):
            pass  # sin validaciones semanticas: solo control transaccional
        else:
            raise SemanticError(f"tipo de nodo desconocido: {type(nodo).__name__}")

    def get_schema(self, tabla: str) -> Schema:
        if not self._catalog.existe_tabla(tabla):
            raise SemanticError(f"la tabla '{tabla}' no existe")
        return self._catalog.get_table(tabla).schema

    def nombres_columnas(self, schema: Schema) -> set:
        nombres = set()
        for col in schema.columns:
            nombres.add(col.name)
        return nombres

    def validar_columna_existe(self, schema: Schema, columna: str) -> None:
        if columna not in self.nombres_columnas(schema):
            raise SemanticError(f"la columna '{columna}' no existe en la tabla '{schema.table_name}'")

    def tipo_compatible(self, tipo: DataType, valor) -> bool:
        tipos_numericos = {DataType.SMALLINT, DataType.INT, DataType.BIGINT, DataType.FLOAT, DataType.DOUBLE}
        tipos_texto = {DataType.CHAR, DataType.VARCHAR}

        if tipo in tipos_numericos:
            return isinstance(valor, (int, float)) and not isinstance(valor, bool)
        if tipo in tipos_texto:
            return isinstance(valor, str)
        if tipo == DataType.BOOL:
            return isinstance(valor, bool)
        return False

    def validar_where(self, schema: Schema, condicion) -> None:
        if isinstance(condicion, BinaryCondition):
            self.validar_where(schema, condicion.izquierda)
            self.validar_where(schema, condicion.derecha)
        elif isinstance(condicion, Condition):
            self.validar_columna_existe(schema, condicion.columna)
            idx = schema.column_index(condicion.columna)
            col = schema.columns[idx]
            if not self.tipo_compatible(col.type, condicion.valor):
                raise SemanticError(f"tipo incompatible en WHERE: la columna '{col.name}' "
                    f"es {col.type.value} pero se comparo con '{condicion.valor}' ({type(condicion.valor).__name__})")
        else:
            raise SemanticError("condicion WHERE erronea")

    def validar_select(self, nodo: SelectNode) -> None:
        schema = self.get_schema(nodo.tabla)

        if nodo.columnas != ["*"]:
            for columna in nodo.columnas:
                self.validar_columna_existe(schema, columna)

        if nodo.where is not None:
            self.validar_where(schema, nodo.where)

        if nodo.order_by is not None:
            self.validar_columna_existe(schema, nodo.order_by.columna)

        if nodo.group_by is not None:
            self.validar_columna_existe(schema, nodo.group_by)

    def validar_insert(self, nodo: InsertNode) -> None:
        schema = self.get_schema(nodo.tabla)

        n_col = len(schema.columns)
        n_val = len(nodo.valores)
        if n_val != n_col:
            raise SemanticError(f"INSERT en '{nodo.tabla}': se esperaban {n_col} valores pero se dieron {n_val}")

        for col, valor in zip(schema.columns, nodo.valores):
            if not self.tipo_compatible(col.type, valor):
                raise SemanticError(f"INSERT en '{nodo.tabla}': la columna '{col.name}' es {col.type.value} "
                    f"pero se dio '{valor}' ({type(valor).__name__})")

    def validar_delete(self, nodo: DeleteNode) -> None:
        schema = self.get_schema(nodo.tabla)
        if nodo.where is not None:
            self.validar_where(schema, nodo.where)