import tempfile

from query.lexer import Lexer, LexerError
from query.parser import Parser, ParserError
from query.semantic import SemanticAnalyzer, SemanticError
from query.catalog import Catalog, TableInfo, STORAGE_HEAP, STORAGE_SEQUENTIAL
from query.ast import SelectNode, InsertNode, DeleteNode, Condition, BinaryCondition
from query.tokens import TokenType
from common.record import Record
from common.types import Column, DataType, Schema
from engine.external import external_group_by, external_sort

BUFFER_PAGES = 64

class ExecutionError(Exception):
    pass

class QueryResult:
    def __init__(self, filas=None, resumen=None, plan=None, error=None, tipo_error=None):
        self.filas = filas
        self.resumen = resumen
        if plan is None:
            self.plan = []
        else:
            self.plan = plan
        self.error = error
        self.tipo_error = tipo_error

    @property
    def ok(self):
        if self.error is None:
            return True
        return False

class Conexion:
    def __init__(self, catalog: Catalog, buffer_pages: int = BUFFER_PAGES, tmp_dir: str | None = None):
        self.catalog = catalog
        self.semantic = SemanticAnalyzer(catalog)
        self.plan = []
        self.buffer_pages = buffer_pages
        self.tmp_dir = tmp_dir

    def execute(self, sql: str) -> QueryResult:
        self.plan = []

        try:
            tokens = Lexer(sql).tokenize()
        except LexerError as e:
            return QueryResult(error=str(e), tipo_error="lexico")

        try:
            nodo = Parser(tokens).parse()
        except ParserError as e:
            return QueryResult(error=str(e), tipo_error="sintactico")

        try:
            self.semantic.validar(nodo)
        except SemanticError as e:
            return QueryResult(error=str(e), tipo_error="semantico")

        try:
            if isinstance(nodo, SelectNode):
                filas = self.ejecutar_select(nodo)
                return QueryResult(filas=filas, plan=self.plan)
            if isinstance(nodo, InsertNode):
                resumen = self.ejecutar_insert(nodo)
                return QueryResult(resumen=resumen, plan=self.plan)
            if isinstance(nodo, DeleteNode):
                resumen = self.ejecutar_delete(nodo)
                return QueryResult(resumen=resumen, plan=self.plan)
            return QueryResult(error=f"nodo no ejecutable: {type(nodo).__name__}", tipo_error="ejecucion")
        except ExecutionError as e:
            return QueryResult(error=str(e), tipo_error="ejecucion", plan=self.plan)

    def leer_todo(self, info: TableInfo):
        nombres_col = [c.name for c in info.schema.columns]
        if info.tipo_storage == STORAGE_HEAP:
            fuente = info.storage.scan(info.schema)
        elif info.tipo_storage == STORAGE_SEQUENTIAL:
            fuente = info.storage.scan()
        else:
            raise ExecutionError(f"storage desconocido: {info.tipo_storage}")
        for record in fuente:
            yield dict(zip(nombres_col, record.values))

    def cumple_where(self, cond, fila: dict) -> bool:
        if isinstance(cond, BinaryCondition):
            lado_izq = self.cumple_where(cond.izquierda, fila)
            lado_der = self.cumple_where(cond.derecha, fila)
            if cond.operador == TokenType.AND:
                return lado_izq and lado_der
            else:
                return lado_izq or lado_der
        if not isinstance(cond, Condition):
            raise ExecutionError("condicion WHERE erronea")

        val_fila = fila[cond.columna]
        val_cond = cond.valor
        op = cond.operador

        if op == TokenType.EQ:
            resultado = (val_fila == val_cond)
        elif op == TokenType.NEQ:
            resultado = (val_fila != val_cond)
        elif op == TokenType.LT:
            resultado = (val_fila < val_cond)
        elif op == TokenType.LTE:
            resultado = (val_fila <= val_cond)
        elif op == TokenType.GT:
            resultado = (val_fila > val_cond)
        elif op == TokenType.GTE:
            resultado = (val_fila >= val_cond)
        else:
            raise ExecutionError(f"operador desconocido: {op}")
        return resultado

    def _extraer_rango_columna(self, cond, col_name: str):
        """Extrae (low, high) de una condición simple o compuesta con AND sobre col_name."""
        if isinstance(cond, Condition):
            if cond.columna == col_name:
                if cond.operador in (TokenType.GT, TokenType.GTE):
                    return (cond.valor, 999999999)
                if cond.operador in (TokenType.LT, TokenType.LTE):
                    return (-999999999, cond.valor)
            return None

        if isinstance(cond, BinaryCondition) and cond.operador == TokenType.AND:
            r1 = self._extraer_rango_columna(cond.izquierda, col_name)
            r2 = self._extraer_rango_columna(cond.derecha, col_name)
            if r1 is not None and r2 is not None:
                low = max(r1[0], r2[0])
                high = min(r1[1], r2[1])
                if low <= high:
                    return (low, high)
            elif r1 is not None:
                return r1
            elif r2 is not None:
                return r2

        return None

    def ejecutar_select(self, nodo: SelectNode) -> list:
        info = self.catalog.get_table(nodo.tabla)
        where = nodo.where
        orden_ya_resuelto = False
        nombres_col = [c.name for c in info.schema.columns]

        if where is None:
            usa_indice_orden = (nodo.order_by is not None and info.tipo_storage == STORAGE_HEAP
                                and self.catalog.tiene_indice(nodo.tabla, nodo.order_by.columna))
            if usa_indice_orden:
                indice, tipo_indice = self.catalog.get_indice(nodo.tabla, nodo.order_by.columna)
            else:
                indice, tipo_indice = None, None

            if usa_indice_orden and tipo_indice == "bplus":
                self.plan.append(f"lectura ordenada por indice bplus no agrupado sobre '{nodo.order_by.columna}'")
                filas = []
                for clave, rid in indice.scan():
                    record = info.storage.read(rid, info.schema)
                    if record is not None:
                        filas.append(dict(zip(nombres_col, record.values)))
                if nodo.order_by.descendente:
                    filas.reverse()
                orden_ya_resuelto = True
            elif nodo.order_by is not None and info.tipo_storage == STORAGE_SEQUENTIAL and nodo.order_by.columna == info.key_column:
                self.plan.append(f"lectura secuencial ordenada de '{info.nombre}' por clave '{nodo.order_by.columna}'")
                filas = list(self.leer_todo(info))
                if nodo.order_by.descendente:
                    filas.reverse()
                orden_ya_resuelto = True
            else:
                self.plan.append(f"escaneo completo de '{info.nombre}' ({info.tipo_storage})")
                filas = list(self.leer_todo(info))
        else:
            es_igualdad = isinstance(where, Condition) and where.operador == TokenType.EQ

            # Evaluar si aplica búsqueda por rango en algún índice (bplus o clustered)
            rango_info = None
            for col in info.indices:
                ind, t_ind = self.catalog.get_indice(nodo.tabla, col)
                if t_ind in ("bplus", "clustered"):
                    bnds = self._extraer_rango_columna(where, col)
                    if bnds is not None:
                        rango_info = (col, ind, t_ind, bnds[0], bnds[1])
                        break

            if es_igualdad and self.catalog.tiene_indice(nodo.tabla, where.columna):
                indice, tipo_indice = self.catalog.get_indice(nodo.tabla, where.columna)
                if tipo_indice == "clustered":
                    self.plan.append(f"busqueda por indice bplus agrupado en '{where.columna}={where.valor}'")
                    record = indice.search(where.valor)
                    filas = [dict(zip(nombres_col, record.values))] if record is not None else []
                elif tipo_indice == "bplus":
                    self.plan.append(f"busqueda por indice bplus no agrupado en '{where.columna}={where.valor}'")
                    rids = indice.search(where.valor)
                    filas = []
                    for rid in rids:
                        record = info.storage.read(rid, info.schema)
                        if record is not None:
                            filas.append(dict(zip(nombres_col, record.values)))
                elif tipo_indice == "hash":
                    self.plan.append(f"busqueda por indice hash en '{where.columna}={where.valor}'")
                    rids = indice.search(where.valor)
                    filas = []
                    for rid in rids:
                        record = info.storage.read(rid, info.schema)
                        if record is not None:
                            filas.append(dict(zip(nombres_col, record.values)))
                else:
                    self.plan.append(f"escaneo completo de '{info.nombre}' ({info.tipo_storage}) + filtro WHERE")
                    filas = [f for f in self.leer_todo(info) if self.cumple_where(where, f)]

            elif es_igualdad and info.tipo_storage == STORAGE_SEQUENTIAL and where.columna == info.key_column:
                self.plan.append(f"busqueda binaria por clave '{info.key_column}={where.valor}' en '{info.nombre}'")
                record = info.storage.search(where.valor)
                filas = [dict(zip(nombres_col, record.values))] if record is not None else []

            elif rango_info is not None:
                col_r, indice_r, tipo_r, low, high = rango_info
                if tipo_r == "clustered":
                    self.plan.append(f"busqueda por rango en indice bplus agrupado sobre '{col_r}' [{low} a {high}]")
                    records = indice_r.range_search(low, high)
                    filas = []
                    for r in records:
                        fila = dict(zip(nombres_col, r.values))
                        if self.cumple_where(where, fila):
                            filas.append(fila)
                elif tipo_r == "bplus":
                    self.plan.append(f"busqueda por rango en indice bplus no agrupado sobre '{col_r}' [{low} a {high}]")
                    rids = indice_r.range_search(low, high)
                    filas = []
                    for rid in rids:
                        record = info.storage.read(rid, info.schema)
                        if record is not None:
                            fila = dict(zip(nombres_col, record.values))
                            if self.cumple_where(where, fila):
                                filas.append(fila)
                else:
                    self.plan.append(f"escaneo completo de '{info.nombre}' ({info.tipo_storage}) + filtro WHERE")
                    filas = [f for f in self.leer_todo(info) if self.cumple_where(where, f)]

            else:
                self.plan.append(f"escaneo completo de '{info.nombre}' ({info.tipo_storage}) + filtro WHERE")
                filas = [f for f in self.leer_todo(info) if self.cumple_where(where, f)]
        # external_sort devuelve un iterador perezoso: materializar antes de salir del with
        with tempfile.TemporaryDirectory(dir=self.tmp_dir) as tmp:
            schema = info.schema
            if nodo.group_by is not None:
                filas, schema = self.agrupar(filas, schema, nodo.group_by, tmp)
                orden_ya_resuelto = False

            if nodo.order_by is not None and not orden_ya_resuelto:
                filas = self.ordenar(filas, schema, nodo.order_by, tmp)

            if nodo.columnas == ["*"]:
                return list(filas)
            salida = []
            for fila in filas:
                fila_reducida = {}
                for col in nodo.columnas:
                    fila_reducida[col] = fila[col]
                salida.append(fila_reducida)
            return salida

    def agrupar(self, filas, schema: Schema, columna: str, tmp_dir: str):
        stats = {}
        conteo = external_group_by(filas, lambda f: f[columna], lambda acc, f: (acc or 0) + 1,
                                   schema, self.buffer_pages, tmp_dir, stats)
        self.plan.append(f"GROUP BY {columna} (external hash, B={self.buffer_pages}: "
                         f"{stats['partitions']} particiones, {stats['repartitions']} reparticiones)")
        col = schema.columns[schema.column_index(columna)]
        schema_grupos = Schema(schema.table_name, [col, Column("count", DataType.BIGINT, 8)])
        return [{columna: clave, "count": n} for clave, n in conteo.items()], schema_grupos

    def ordenar(self, filas, schema: Schema, order_by, tmp_dir: str):
        stats = {}
        filas = external_sort(filas, lambda f: f[order_by.columna], schema, self.buffer_pages,
                              tmp_dir, reverse=order_by.descendente, stats=stats)
        direccion = "DESC" if order_by.descendente else "ASC"
        self.plan.append(f"ORDER BY {order_by.columna} {direccion} (external sort, B={self.buffer_pages}: "
                         f"{stats['runs']} runs, {stats['passes']} pasadas)")
        return filas

    def ejecutar_insert(self, nodo: InsertNode) -> dict:
        info = self.catalog.get_table(nodo.tabla)
        record = Record(nodo.valores)

        if info.tipo_storage == STORAGE_HEAP:
            pk_col = None
            for col in info.schema.columns:
                if col.is_pk:
                    pk_col = col
                    break
            if pk_col is not None:
                idx_pk = info.schema.column_index(pk_col.name)
                nueva_pk = record.values[idx_pk]
                for fila in self.leer_todo(info):
                    if fila[pk_col.name] == nueva_pk:
                        raise ExecutionError(f"no se pudo insertar: clave {nueva_pk} ya existe")
        try:
            if info.tipo_storage == STORAGE_HEAP:
                rid = info.storage.insert(record, info.schema)
                self.actualizar_indices_insert(nodo.tabla, info, record, rid)
            elif info.tipo_storage == STORAGE_SEQUENTIAL:
                info.storage.insert(record)
            else:
                raise ExecutionError(f"storage desconocido: {info.tipo_storage}")
        except ValueError as e:
            raise ExecutionError(f"no se pudo insertar: {e}")

        self.plan.append(f"INSERT en '{info.nombre}' ({info.tipo_storage})")
        return {"operacion": "INSERT", "filas_afectadas": 1}

    def actualizar_indices_insert(self, tabla: str, info: TableInfo, record: Record, rid) -> None:
        for columna in info.indices:
            indice, tipo_indice = self.catalog.get_indice(tabla, columna)
            if tipo_indice == "clustered":
                continue
            idx = info.schema.column_index(columna)
            valor = record.values[idx]
            indice.insert(valor, rid)

    def ejecutar_delete(self, nodo: DeleteNode) -> dict:
        info = self.catalog.get_table(nodo.tabla)
        where = nodo.where
        if where is not None:
            es_por_clave = (
                isinstance(where, Condition)
                and where.operador == TokenType.EQ
                and where.columna == info.key_column
                and info.tipo_storage == STORAGE_SEQUENTIAL
            )
            if es_por_clave:
                clave = where.valor
                self.plan.append(f"DELETE por clave '{info.key_column}={clave}' en '{info.nombre}'")
                borrado = info.storage.delete(clave)
                if borrado:
                    return {"operacion": "DELETE", "filas_afectadas": 1}
                else:
                    return {"operacion": "DELETE", "filas_afectadas": 0}

        if info.tipo_storage == STORAGE_SEQUENTIAL:
            claves = []
            for fila in self.leer_todo(info):
                if where is None or self.cumple_where(where, fila):
                    claves.append(fila[info.key_column])
            for clave in claves:
                info.storage.delete(clave)
            self.plan.append(f"escaneo + DELETE por clave en '{info.nombre}'")
            return {"operacion": "DELETE", "filas_afectadas": len(claves)}

        if info.tipo_storage == STORAGE_HEAP:
            nombres_col = [c.name for c in info.schema.columns]
            candidatos = []
            for rid, record in info.storage.scan_con_rid(info.schema):
                fila = dict(zip(nombres_col, record.values))
                if where is None or self.cumple_where(where, fila):
                    candidatos.append((rid, record))
            for rid, record in candidatos:
                self.actualizar_indices_delete(nodo.tabla, info, record, rid)
                info.storage.delete(rid)
            self.plan.append(f"escaneo + DELETE por RID en '{info.nombre}'")
            return {"operacion": "DELETE", "filas_afectadas": len(candidatos)}

        raise ExecutionError(f"storage desconocido: {info.tipo_storage}")

    def actualizar_indices_delete(self, tabla: str, info: TableInfo, record: Record, rid) -> None:
        for columna in info.indices:
            indice, tipo_indice = self.catalog.get_indice(tabla, columna)
            if tipo_indice == "clustered":
                continue
            idx = info.schema.column_index(columna)
            valor = record.values[idx]
            indice.delete(valor, rid)