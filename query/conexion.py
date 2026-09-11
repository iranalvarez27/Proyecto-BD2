from query.lexer import Lexer, LexerError
from query.parser import Parser, ParserError
from query.semantic import SemanticAnalyzer, SemanticError
from query.catalog import Catalog, TableInfo, STORAGE_HEAP, STORAGE_SEQUENTIAL
from query.ast import SelectNode, InsertNode, DeleteNode, Condition, BinaryCondition
from query.tokens import TokenType
from common.record import Record

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
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.semantic = SemanticAnalyzer(catalog)
        self.plan = []

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

    def ejecutar_select(self, nodo: SelectNode) -> list:
        info = self.catalog.get_table(nodo.tabla)
        where = nodo.where
        if where is None:
            self.plan.append(f"escaneo completo de '{info.nombre}' ({info.tipo_storage})")
            filas = list(self.leer_todo(info))
        else:
            es_por_clave = (isinstance(where, Condition) and where.operador == TokenType.EQ
                and where.columna == info.key_column and info.tipo_storage == STORAGE_SEQUENTIAL)
            if es_por_clave:
                clave = where.valor
                self.plan.append(f"busqueda binaria por clave '{info.key_column}={clave}' en '{info.nombre}'")
                record = info.storage.search(clave)
                if record is None:
                    filas = []
                else:
                    nombres_col = [c.name for c in info.schema.columns]
                    filas = [dict(zip(nombres_col, record.values))]
            else:
                self.plan.append(f"escaneo completo de '{info.nombre}' ({info.tipo_storage}) + filtro WHERE")
                filas = []
                for fila in self.leer_todo(info):
                    if self.cumple_where(where, fila):
                        filas.append(fila)
        if nodo.group_by is not None:
            filas = self.agrupar(filas, nodo.group_by)
            self.plan.append(f"GROUP BY {nodo.group_by}")

        if nodo.order_by is not None:
            filas = sorted(filas, key=lambda f: f[nodo.order_by.columna], reverse=nodo.order_by.descendente)
            if nodo.order_by.descendente:
                direccion = "DESC"
            else:
                direccion = "ASC"
            self.plan.append(f"ORDER BY {nodo.order_by.columna} {direccion}")
        if nodo.columnas == ["*"]:
            return filas
        salida = []
        for fila in filas:
            fila_reducida = {}
            for col in nodo.columnas:
                fila_reducida[col] = fila[col]
            salida.append(fila_reducida)
        return salida

    def agrupar(self, filas: list, columna: str) -> list:
        conteo = {}
        orden_aparicion = []
        for fila in filas:
            clave = fila[columna]
            if clave not in conteo:
                conteo[clave] = 0
                orden_aparicion.append(clave)
            conteo[clave] += 1
        salida = []
        for clave in orden_aparicion:
            salida.append({columna: clave, "count": conteo[clave]})
        return salida

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
                info.storage.insert(record, info.schema)
            elif info.tipo_storage == STORAGE_SEQUENTIAL:
                info.storage.insert(record)
            else:
                raise ExecutionError(f"storage desconocido: {info.tipo_storage}")
        except ValueError as e:
            raise ExecutionError(f"no se pudo insertar: {e}")

        self.plan.append(f"INSERT en '{info.nombre}' ({info.tipo_storage})")
        return {"operacion": "INSERT", "filas_afectadas": 1}

    def ejecutar_delete(self, nodo: DeleteNode) -> dict:
        info = self.catalog.get_table(nodo.tabla)
        where = nodo.where
        if where is not None:
            es_por_clave = (isinstance(where, Condition) and where.operador == TokenType.EQ
                and where.columna == info.key_column and info.tipo_storage == STORAGE_SEQUENTIAL)
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
            rids = []
            for rid, record in info.storage.scan_con_rid(info.schema):
                fila = dict(zip(nombres_col, record.values))
                if where is None or self.cumple_where(where, fila):
                    rids.append(rid)
            for rid in rids:
                info.storage.delete(rid)
            self.plan.append(f"escaneo + DELETE por RID en '{info.nombre}'")
            return {"operacion": "DELETE", "filas_afectadas": len(rids)}
        raise ExecutionError(f"storage desconocido: {info.tipo_storage}")