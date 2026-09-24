from query.ast import (
    SelectNode, InsertNode, DeleteNode, UpdateNode, Condition, NotCondition, BinaryCondition, OrderBy,
    BeginNode, CommitNode, RollbackNode, ExplainNode, CreateTableNode, DropTableNode,
    PointLiteral, PolygonLiteral, FuncCall, SpatialCondition, CreateIndexNode,
    AggregateCall, ColumnRef, SubquerySelect,
)
from query.tokens import TokenType
from query.catalog import Catalog, INDEX_RTREE
from common.types import Schema, DataType


class SemanticError(Exception):
    pass

TAMANOS_POR_DEFECTO = {DataType.INT: 4, DataType.SMALLINT: 2, DataType.BIGINT: 8, DataType.FLOAT: 4, DataType.DOUBLE: 8, DataType.BOOL: 1, DataType.POINT: 16,}

FUNCIONES_DISTANCIA = {"distancia", "distancia_geo", "distancia_haversine", "distancia_euclidiana"}
FUNCIONES_POLIGONO = {"dentro_de"}
FUNCIONES_ESPACIALES = FUNCIONES_DISTANCIA | FUNCIONES_POLIGONO
FUNCIONES_AGREGADAS = {"count", "sum", "avg"}
TIPOS_NUMERICOS = {DataType.SMALLINT, DataType.INT, DataType.BIGINT, DataType.FLOAT, DataType.DOUBLE}

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
        elif isinstance(nodo, UpdateNode):
            self.validar_update(nodo)
        elif isinstance(nodo, ExplainNode):
            self.validar(nodo.statement)  
        elif isinstance(nodo, CreateTableNode):
            self.validar_create_table(nodo)
        elif isinstance(nodo, DropTableNode):
            self.validar_drop_table(nodo)
        elif isinstance(nodo, CreateIndexNode):
            self.validar_create_index(nodo)
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
        if tipo == DataType.POINT:
            return isinstance(valor, PointLiteral) or (
                isinstance(valor, (tuple, list)) and len(valor) == 2
            )
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

    def _validar_valor_columna(self, schema: Schema, col, valor) -> None:
        if isinstance(valor, ColumnRef):
            self.validar_columna_existe(schema, valor.nombre)
            col2 = schema.columns[schema.column_index(valor.nombre)]
            if col2.type == DataType.POINT:
                raise SemanticError(f"la columna '{col2.name}' es POINT: usa distancia(...) o dentro_de(...)")
            if not self._tipos_unificables(col.type, col2.type):
                raise SemanticError(f"comparacion invalida: '{col.name}' es {col.type.value} "
                    f"pero '{valor.nombre}' es {col2.type.value}")
            return
        if not self.tipo_compatible(col.type, valor):
            raise SemanticError(f"tipo incompatible en WHERE: la columna '{col.name}' "
                f"es {col.type.value} pero se comparo con '{valor}' ({type(valor).__name__})")

    def _resolver_columna_multi(self, columna: str, tablas_schemas: dict):
        if "." not in columna:
            ejemplo = next(iter(tablas_schemas))
            raise SemanticError(f"la columna '{columna}' debe calificarse con su tabla (ej. '{ejemplo}.{columna}') "
                "en una consulta con JOIN")
        tabla_ref, col = columna.split(".", 1)
        schema = tablas_schemas.get(tabla_ref)
        if schema is None:
            raise SemanticError(f"'{tabla_ref}' no es ninguna de las tablas de este JOIN "
                f"({', '.join(tablas_schemas)})")
        self.validar_columna_existe(schema, col)
        return tabla_ref, schema, col

    def _validar_where_multi(self, condicion, tablas_schemas: dict) -> None:
        if isinstance(condicion, BinaryCondition):
            self._validar_where_multi(condicion.izquierda, tablas_schemas)
            self._validar_where_multi(condicion.derecha, tablas_schemas)
        elif isinstance(condicion, NotCondition):
            self._validar_where_multi(condicion.interior, tablas_schemas)
        elif isinstance(condicion, Condition):
            _, schema, col = self._resolver_columna_multi(condicion.columna, tablas_schemas)
            campo = schema.columns[schema.column_index(col)]
            if isinstance(condicion.valor, ColumnRef):
                raise SemanticError("comparacion columna-contra-columna en el WHERE de un JOIN todavia no esta soportada")
            if condicion.operador == TokenType.LIKE:
                if campo.type not in (DataType.CHAR, DataType.VARCHAR):
                    raise SemanticError(f"LIKE solo aplica a columnas de texto: '{condicion.columna}' es {campo.type.value}")
                if not isinstance(condicion.valor, str):
                    raise SemanticError("el patron de LIKE debe ser un texto entre comillas")
            elif condicion.operador == TokenType.IN:
                if isinstance(condicion.valor, SubquerySelect):
                    raise SemanticError("una subconsulta IN (...) todavia no esta soportada dentro del WHERE de un JOIN")
                if not isinstance(condicion.valor, (list, tuple)) or not condicion.valor:
                    raise SemanticError("IN (...) necesita al menos un valor")
                for v in condicion.valor:
                    if not self.tipo_compatible(campo.type, v):
                        raise SemanticError(f"tipo incompatible en WHERE: la columna '{condicion.columna}' "
                            f"es {campo.type.value} pero IN (...) trae '{v}' ({type(v).__name__})")
            elif not self.tipo_compatible(campo.type, condicion.valor):
                raise SemanticError(f"tipo incompatible en WHERE: la columna '{condicion.columna}' "
                    f"es {campo.type.value} pero se comparo con '{condicion.valor}' ({type(condicion.valor).__name__})")
        else:
            raise SemanticError("condicion WHERE erronea")

    def validar_join(self, nodo: SelectNode, schema: Schema) -> None:
        tablas_schemas = {nodo.tabla: schema}

        for join in nodo.joins:
            if join.tabla in tablas_schemas:
                raise SemanticError(f"la tabla '{join.tabla}' ya esta unida en esta consulta")
            schema_nueva = self.get_schema(join.tabla)
            tablas_previas = dict(tablas_schemas)
            tablas_schemas[join.tabla] = schema_nueva

            tabla_izq, schema_izq, col_izq = self._resolver_columna_multi(join.columna_izquierda, tablas_schemas)
            tabla_der, schema_der, col_der = self._resolver_columna_multi(join.columna_derecha, tablas_schemas)
            if tabla_izq == tabla_der:
                raise SemanticError("la condicion ON de un JOIN debe comparar una columna de cada tabla")
            if join.tabla not in (tabla_izq, tabla_der):
                raise SemanticError(f"la condicion ON de JOIN {join.tabla} debe referenciar a la tabla recien unida")
            if tabla_izq != join.tabla and tabla_izq not in tablas_previas:
                raise SemanticError(f"'{tabla_izq}' no se puede usar en el ON: aun no fue unida")
            if tabla_der != join.tabla and tabla_der not in tablas_previas:
                raise SemanticError(f"'{tabla_der}' no se puede usar en el ON: aun no fue unida")

            tipo_izq = schema_izq.columns[schema_izq.column_index(col_izq)].type
            tipo_der = schema_der.columns[schema_der.column_index(col_der)].type
            if not self._tipos_unificables(tipo_izq, tipo_der):
                raise SemanticError(f"JOIN ON con tipos incompatibles: '{join.columna_izquierda}' es {tipo_izq.value} "
                    f"y '{join.columna_derecha}' es {tipo_der.value}")

        if nodo.columnas != ["*"]:
            for columna in nodo.columnas:
                if isinstance(columna, AggregateCall):
                    raise SemanticError("las funciones agregadas junto con JOIN todavia no estan soportadas")
                self._resolver_columna_multi(columna, tablas_schemas)

        if nodo.where is not None:
            self._validar_where_multi(nodo.where, tablas_schemas)

        if nodo.order_by is not None:
            if nodo.order_by.funcion is not None:
                raise SemanticError("ORDER BY con funcion espacial junto con JOIN todavia no esta soportado")
            self._resolver_columna_multi(nodo.order_by.columna, tablas_schemas)

        if nodo.group_by is not None:
            self._resolver_columna_multi(nodo.group_by, tablas_schemas)

    def _resolver_tipo_arg_punto(self, schema: Schema, arg) -> None:
        if isinstance(arg, PointLiteral):
            return
        if isinstance(arg, str):
            self.validar_columna_existe(schema, arg)
            idx = schema.column_index(arg)
            col = schema.columns[idx]
            if col.type != DataType.POINT:
                raise SemanticError(f"'{arg}' no es una columna POINT (es {col.type.value})")
            return
        raise SemanticError(f"se esperaba una columna POINT o un literal POINT(...), se dio '{arg}'")

    def validar_func_espacial(self, schema: Schema, funcion: FuncCall) -> None:
        if funcion.nombre not in FUNCIONES_ESPACIALES:
            disponibles = ", ".join(sorted(FUNCIONES_ESPACIALES))
            raise SemanticError(f"funcion desconocida '{funcion.nombre}' (disponibles: {disponibles})")

        if funcion.nombre in FUNCIONES_DISTANCIA:
            if len(funcion.argumentos) != 2:
                raise SemanticError(f"{funcion.nombre}(...) necesita exactamente 2 argumentos (columna POINT, punto)")
            self._resolver_tipo_arg_punto(schema, funcion.argumentos[0])
            self._resolver_tipo_arg_punto(schema, funcion.argumentos[1])
        elif funcion.nombre in FUNCIONES_POLIGONO:
            if len(funcion.argumentos) != 2:
                raise SemanticError(f"{funcion.nombre}(...) necesita exactamente 2 argumentos (columna POINT, poligono)")
            self._resolver_tipo_arg_punto(schema, funcion.argumentos[0])
            if not isinstance(funcion.argumentos[1], PolygonLiteral):
                raise SemanticError(f"{funcion.nombre}(...): el segundo argumento debe ser POLYGON(...)")

    def validar_spatial_condition(self, schema: Schema, condicion: SpatialCondition) -> None:
        self.validar_func_espacial(schema, condicion.funcion)
        if condicion.operador is not None:
            if condicion.funcion.nombre in FUNCIONES_POLIGONO:
                raise SemanticError(f"{condicion.funcion.nombre}(...) ya es un predicado booleano, no se compara con operadores")
            if not isinstance(condicion.valor, (int, float)) or isinstance(condicion.valor, bool):
                raise SemanticError(f"la comparacion de {condicion.funcion.nombre}(...) necesita un valor numerico, "
                    f"se dio '{condicion.valor}' ({type(condicion.valor).__name__})")

    def validar_where(self, schema: Schema, condicion) -> None:
        if isinstance(condicion, BinaryCondition):
            self.validar_where(schema, condicion.izquierda)
            self.validar_where(schema, condicion.derecha)
        elif isinstance(condicion, NotCondition):
            self.validar_where(schema, condicion.interior)
        elif isinstance(condicion, SpatialCondition):
            self.validar_spatial_condition(schema, condicion)
        elif isinstance(condicion, Condition):
            self.validar_columna_existe(schema, condicion.columna)
            idx = schema.column_index(condicion.columna)
            col = schema.columns[idx]
            if col.type == DataType.POINT:
                raise SemanticError(f"la columna '{col.name}' es POINT: usa distancia(...) o dentro_de(...) en vez de "
                    f"comparar directamente con '{condicion.valor}'")

            if condicion.operador == TokenType.LIKE:
                if col.type not in (DataType.CHAR, DataType.VARCHAR):
                    raise SemanticError(f"LIKE solo aplica a columnas de texto (CHAR/VARCHAR): "
                        f"'{col.name}' es {col.type.value}")
                if not isinstance(condicion.valor, str):
                    raise SemanticError("el patron de LIKE debe ser un texto entre comillas")
            elif condicion.operador == TokenType.IN:
                valores = condicion.valor
                if isinstance(valores, SubquerySelect):
                    subnodo = valores.nodo_select
                    if subnodo.joins:
                        raise SemanticError("una subconsulta de IN (...) con JOIN todavia no esta soportada")
                    if (subnodo.columnas == ["*"] or len(subnodo.columnas) != 1
                            or isinstance(subnodo.columnas[0], AggregateCall)):
                        raise SemanticError("la subconsulta de IN (...) debe seleccionar exactamente "
                            "1 columna simple (sin funciones agregadas)")
                    self.validar_select(subnodo)
                    schema_sub = self.get_schema(subnodo.tabla)
                    col_sub = schema_sub.columns[schema_sub.column_index(subnodo.columnas[0])]
                    if not self._tipos_unificables(col.type, col_sub.type):
                        raise SemanticError(f"la subconsulta de IN (...) devuelve {col_sub.type.value} "
                            f"pero se compara con '{col.name}' ({col.type.value})")
                elif not isinstance(valores, (list, tuple)) or not valores:
                    raise SemanticError("IN (...) necesita al menos un valor")
                else:
                    for v in valores:
                        self._validar_valor_columna(schema, col, v)
            else:
                self._validar_valor_columna(schema, col, condicion.valor)
        else:
            raise SemanticError("condicion WHERE erronea")

    def validar_aggregate(self, schema: Schema, ag: AggregateCall) -> None:
        if ag.nombre not in FUNCIONES_AGREGADAS:
            raise SemanticError(f"funcion desconocida '{ag.nombre}' en el SELECT "
                f"(disponibles: {', '.join(sorted(FUNCIONES_AGREGADAS))})")
        if ag.columna == "*":
            if ag.nombre != "count":
                raise SemanticError(f"{ag.nombre}(*) no es valido: solo COUNT(*) admite '*'")
            return
        self.validar_columna_existe(schema, ag.columna)
        col = schema.columns[schema.column_index(ag.columna)]
        if ag.nombre in ("sum", "avg") and col.type not in TIPOS_NUMERICOS:
            raise SemanticError(f"{ag.nombre}({ag.columna}) necesita una columna numerica, "
                f"'{ag.columna}' es {col.type.value}")

    def validar_select(self, nodo: SelectNode) -> None:
        schema = self.get_schema(nodo.tabla)

        if nodo.joins:
            self.validar_join(nodo, schema)
            return

        columnas_planas = [c for c in nodo.columnas if isinstance(c, str)] if nodo.columnas != ["*"] else []
        agregados = [c for c in nodo.columnas if isinstance(c, AggregateCall)] if nodo.columnas != ["*"] else []

        for columna in columnas_planas:
            self.validar_columna_existe(schema, columna)
        for ag in agregados:
            self.validar_aggregate(schema, ag)

        if agregados:
            if nodo.group_by is not None:
                for columna in columnas_planas:
                    if columna != nodo.group_by:
                        raise SemanticError(f"'{columna}' debe estar en GROUP BY o dentro de una funcion agregada")
            elif columnas_planas:
                raise SemanticError("no se pueden combinar columnas sueltas con funciones agregadas sin GROUP BY")

        if nodo.where is not None:
            self.validar_where(schema, nodo.where)

        if nodo.order_by is not None:
            if nodo.order_by.funcion is not None:
                self.validar_func_espacial(schema, nodo.order_by.funcion)
            else:
                self.validar_columna_existe(schema, nodo.order_by.columna)

        if nodo.group_by is not None:
            self.validar_columna_existe(schema, nodo.group_by)

        if nodo.limit is not None and nodo.limit <= 0:
            raise SemanticError(f"LIMIT debe ser un entero positivo, se dio {nodo.limit}")

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

    def validar_update(self, nodo: UpdateNode) -> None:
        schema = self.get_schema(nodo.tabla)
        if not nodo.asignaciones:
            raise SemanticError(f"UPDATE '{nodo.tabla}' necesita al menos un SET columna=valor")

        vistas = set()
        for columna, valor in nodo.asignaciones:
            self.validar_columna_existe(schema, columna)
            if columna in vistas:
                raise SemanticError(f"la columna '{columna}' esta repetida en el SET")
            vistas.add(columna)
            col = schema.columns[schema.column_index(columna)]
            if col.is_pk:
                raise SemanticError(f"no se puede modificar '{columna}': es la PRIMARY KEY de '{nodo.tabla}' "
                    "(borra e inserta de nuevo la fila si necesitas cambiar la clave)")
            if not self.tipo_compatible(col.type, valor):
                raise SemanticError(f"UPDATE '{nodo.tabla}': la columna '{columna}' es {col.type.value} "
                    f"pero se dio '{valor}' ({type(valor).__name__})")

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

    def validar_drop_table(self, nodo: DropTableNode) -> None:
        if not self._catalog.existe_tabla(nodo.tabla):
            raise SemanticError(f"la tabla '{nodo.tabla}' no existe")

    def validar_create_index(self, nodo: CreateIndexNode) -> None:
        schema = self.get_schema(nodo.tabla)
        self.validar_columna_existe(schema, nodo.columna)
        if self._catalog.tiene_indice(nodo.tabla, nodo.columna):
            raise SemanticError(f"la columna '{nodo.columna}' de '{nodo.tabla}' ya tiene un indice")

        col = schema.columns[schema.column_index(nodo.columna)]
        if nodo.tipo_indice == INDEX_RTREE:
            if col.type != DataType.POINT:
                raise SemanticError(f"CREATE INDEX ... USING RTREE solo aplica a columnas POINT "
                    f"('{nodo.columna}' es {col.type.value})")
        elif col.type == DataType.POINT:
            raise SemanticError(f"la columna '{nodo.columna}' es POINT: usa USING RTREE (no BTREE/HASH)")