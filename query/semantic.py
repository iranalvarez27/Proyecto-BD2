from query.ast import (
    SelectNode, InsertNode, DeleteNode, Condition, BinaryCondition, OrderBy,
    BeginNode, CommitNode, RollbackNode, ExplainNode, CreateTableNode,
)
from query.catalog import Catalog
from common.types import Schema, DataType


class SemanticError(Exception):
    pass

TAMANOS_POR_DEFECTO = {DataType.INT: 4, DataType.SMALLINT: 2, DataType.BIGINT: 8, DataType.FLOAT: 4, DataType.DOUBLE: 8, DataType.BOOL: 1,}

def resolver_tipo_columna(tipo_texto: str, tamano: int | None) -> tuple[DataType, int]:
    try:
        tipo = DataType(tipo_texto.upper())
    except ValueError:
        tipos_validos = ", ".join(t.value for t in DataType)
        raise SemanticError(f"tipo de dato desconocido: '{tipo_texto}' (validos: {tipos_validos})")

    if tipo in (DataType.CHAR, DataType.VARCHAR):
        if not tamano or tamano <= 0:
            raise SemanticError(
                f"la columna de tipo {tipo.value} necesita un tamano explicito, ej. {tipo.value}(50)")
        return tipo, tamano

    if tamano is not None and tamano != TAMANOS_POR_DEFECTO[tipo]:
        raise SemanticError(
            f"el tipo {tipo.value} no acepta un tamano explicito (usa {tipo.value} sin parentesis)")
    return tipo, TAMANOS_POR_DEFECTO[tipo]


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
        elif isinstance(nodo, ExplainNode):
            self.validar(nodo.statement)  
        elif isinstance(nodo, CreateTableNode):
            self.validar_create_table(nodo)
        elif isinstance(nodo, (BeginNode, CommitNode, RollbackNode)):
            pass
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

    def _tipos_unificables(self, a: DataType, b: DataType) -> bool:
        numericos = {DataType.SMALLINT, DataType.INT, DataType.BIGINT, DataType.FLOAT, DataType.DOUBLE}
        textos = {DataType.CHAR, DataType.VARCHAR}
        if a == b:
            return True
        if a in numericos and b in numericos:
            return True
        if a in textos and b in textos:
            return True
        return False

    def _resolver_columna_join(self, columna: str, tabla1: str, schema1: Schema, tabla2: str, schema2: Schema):
        if "." not in columna:
            raise SemanticError(f"la columna '{columna}' debe calificarse con su tabla (ej. '{tabla1}.{columna}') "
                "en una consulta con JOIN")
        tabla_ref, col = columna.split(".", 1)
        if tabla_ref == tabla1:
            schema = schema1
        elif tabla_ref == tabla2:
            schema = schema2
        else:
            raise SemanticError(f"'{tabla_ref}' no es ninguna de las tablas de este JOIN ({tabla1}, {tabla2})")
        self.validar_columna_existe(schema, col)
        return schema, col

    def _validar_where_join(self, condicion, tabla1: str, schema1: Schema, tabla2: str, schema2: Schema) -> None:
        if isinstance(condicion, BinaryCondition):
            self._validar_where_join(condicion.izquierda, tabla1, schema1, tabla2, schema2)
            self._validar_where_join(condicion.derecha, tabla1, schema1, tabla2, schema2)
        elif isinstance(condicion, Condition):
            schema, col = self._resolver_columna_join(condicion.columna, tabla1, schema1, tabla2, schema2)
            campo = schema.columns[schema.column_index(col)]
            if not self.tipo_compatible(campo.type, condicion.valor):
                raise SemanticError(f"tipo incompatible en WHERE: la columna '{condicion.columna}' "
                    f"es {campo.type.value} pero se comparo con '{condicion.valor}' ({type(condicion.valor).__name__})")
        else:
            raise SemanticError("condicion WHERE erronea")

    def validar_join(self, nodo: SelectNode, schema: Schema) -> None:
        if nodo.join.tabla == nodo.tabla:
            raise SemanticError("un JOIN no puede unir una tabla consigo misma")
        schema2 = self.get_schema(nodo.join.tabla)

        schema_izq, col_izq = self._resolver_columna_join(
            nodo.join.columna_izquierda, nodo.tabla, schema, nodo.join.tabla, schema2)
        schema_der, col_der = self._resolver_columna_join(
            nodo.join.columna_derecha, nodo.tabla, schema, nodo.join.tabla, schema2)
        if schema_izq is schema_der:
            raise SemanticError("la condicion ON de un JOIN debe comparar una columna de cada tabla")

        tipo_izq = schema_izq.columns[schema_izq.column_index(col_izq)].type
        tipo_der = schema_der.columns[schema_der.column_index(col_der)].type
        if not self._tipos_unificables(tipo_izq, tipo_der):
            raise SemanticError(f"JOIN ON con tipos incompatibles: '{nodo.join.columna_izquierda}' es {tipo_izq.value} y '{nodo.join.columna_derecha}' es {tipo_der.value}")

        if nodo.columnas != ["*"]:
            for columna in nodo.columnas:
                self._resolver_columna_join(columna, nodo.tabla, schema, nodo.join.tabla, schema2)

        if nodo.where is not None:
            self._validar_where_join(nodo.where, nodo.tabla, schema, nodo.join.tabla, schema2)

        if nodo.order_by is not None:
            self._resolver_columna_join(nodo.order_by.columna, nodo.tabla, schema, nodo.join.tabla, schema2)

        if nodo.group_by is not None:
            self._resolver_columna_join(nodo.group_by, nodo.tabla, schema, nodo.join.tabla, schema2)

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

        if nodo.join is not None:
            self.validar_join(nodo, schema)
            return

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

    def validar_create_table(self, nodo: CreateTableNode) -> None:
        if self._catalog.existe_tabla(nodo.tabla):
            raise SemanticError(f"la tabla '{nodo.tabla}' ya existe")
        if not nodo.columnas:
            raise SemanticError(f"CREATE TABLE '{nodo.tabla}' necesita al menos una columna")

        nombres_vistos = set()
        pk_count = 0
        for col_def in nodo.columnas:
            if col_def.nombre in nombres_vistos:
                raise SemanticError(f"la columna '{col_def.nombre}' esta repetida en CREATE TABLE '{nodo.tabla}'")
            nombres_vistos.add(col_def.nombre)
            resolver_tipo_columna(col_def.tipo, col_def.tamano)
            if col_def.is_pk:
                pk_count += 1

        if pk_count == 0:
            raise SemanticError(f"CREATE TABLE '{nodo.tabla}' necesita exactamente una columna PRIMARY KEY")
        if pk_count > 1:
            raise SemanticError(f"CREATE TABLE '{nodo.tabla}' solo admite una columna PRIMARY KEY")