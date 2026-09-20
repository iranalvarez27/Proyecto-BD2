import math
import os
import tempfile
import threading
import time
from query.lexer import Lexer, LexerError
from query.parser import Parser, ParserError
from query.semantic import SemanticAnalyzer, SemanticError, resolver_tipo_columna
from query.catalog import (Catalog, TableInfo, STORAGE_HEAP, STORAGE_SEQUENTIAL, INDEX_BPLUS, INDEX_HASH, INDEX_CLUSTERED, INDEX_RTREE,)
from query.ast import (SelectNode, InsertNode, DeleteNode, Condition, BinaryCondition,BeginNode, CommitNode,RollbackNode, ExplainNode, CreateTableNode, DropTableNode,
                        PointLiteral, PolygonLiteral, FuncCall, SpatialCondition, CreateIndexNode,)
from query.tokens import TokenType
from common.record import Record
from common.types import Column, DataType, Schema
from engine.external import external_group_by, external_hash_join, external_sort
from index.bplus_tree import BPlusTree, DuplicateKey
from index.clustered_bplus_tree import ClusteredBPlusTree
from index.extendible_hash import ExtendibleHash
from index.hash_utils import UnhashableKeyType
from index.key_codec import INT64_MAX, INT64_MIN, KeyTooLong, KeyTypeMismatch, UnorderableKey
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile
from transaction.manager import TransactionManager, TransactionError
from transaction.locks import DeadlockError, LockTimeoutError

BUFFER_PAGES = 64
DEFAULT_SESSION = "__autocommit__"

EARTH_RADIUS_M = 6371000.0
METROS_POR_GRADO = 111320.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _euclidiana_aprox_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * METROS_POR_GRADO * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * METROS_POR_GRADO
    return math.sqrt(dx * dx + dy * dy)


def _punto_en_poligono(lat: float, lon: float, vertices: list) -> bool:
    # ray-casting
    dentro = False
    n = len(vertices)
    for i in range(n):
        lat1, lon1 = vertices[i]
        lat2, lon2 = vertices[(i + 1) % n]
        interseca = ((lon1 > lon) != (lon2 > lon)) and (
            lat < (lat2 - lat1) * (lon - lon1) / (lon2 - lon1) + lat1
        )
        if interseca:
            dentro = not dentro
    return dentro

class ExecutionError(Exception):
    pass

ERRORES_EJECUCION = (ExecutionError, DuplicateKey, UnhashableKeyType, KeyTooLong, KeyTypeMismatch, UnorderableKey,)
class QueryResult:
    def __init__(self, filas=None, resumen=None, plan=None, error=None, tipo_error=None, transaccion_activa=False, xact_id=None):
        self.filas = filas
        self.resumen = resumen
        if plan is None:
            self.plan = []
        else:
            self.plan = plan
        self.error = error
        self.tipo_error = tipo_error
        self.transaccion_activa = transaccion_activa
        self.xact_id = xact_id

    @property
    def ok(self):
        if self.error is None:
            return True
        return False

class Conexion:
    def __init__(self, catalog: Catalog, txn_manager: TransactionManager | None = None,
                 buffer_pages: int = BUFFER_PAGES, tmp_dir: str | None = None,
                 pool=None, data_dir: str | None = None):
        self.catalog = catalog
        self.semantic = SemanticAnalyzer(catalog)
        self.buffer_pages = buffer_pages
        self.tmp_dir = tmp_dir
        self.pool = pool
        self.data_dir = data_dir
        self.txn_manager = txn_manager or TransactionManager()
        self.lock_manager = self.txn_manager.lock_manager
        self._local = threading.local()

    @property
    def plan(self) -> list:
        if not hasattr(self._local, "plan"):
            self._local.plan = []
        return self._local.plan

    @plan.setter
    def plan(self, value: list) -> None:
        self._local.plan = value

    def execute(self, sql: str, session_id: str = DEFAULT_SESSION) -> QueryResult:
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

        if isinstance(nodo, BeginNode):
            return self._ejecutar_begin(session_id)
        if isinstance(nodo, CommitNode):
            return self._ejecutar_commit(session_id)
        if isinstance(nodo, RollbackNode):
            return self._ejecutar_rollback(session_id)
        if isinstance(nodo, ExplainNode):
            return self._ejecutar_explain(nodo, session_id)

        if not isinstance(nodo, (SelectNode, InsertNode, DeleteNode, CreateTableNode, DropTableNode, CreateIndexNode)):
            return QueryResult(error=f"nodo no ejecutable: {type(nodo).__name__}", tipo_error="ejecucion")

        modo = "S" if isinstance(nodo, SelectNode) else "X"
        recursos = [nodo.tabla]
        if isinstance(nodo, SelectNode) and nodo.join is not None and nodo.join.tabla != nodo.tabla:
            recursos.append(nodo.join.tabla)
        txn_estaba_activa = self.txn_manager.is_active(session_id)

        try:
            for recurso in recursos:
                self.lock_manager.acquire(session_id, recurso, modo)
        except (DeadlockError, LockTimeoutError) as e:
            self.txn_manager.abortar_por_deadlock_o_timeout(session_id)
            self._resync_tras_rollback()
            if not txn_estaba_activa:
                for recurso in recursos:
                    self.lock_manager.release_resource(session_id, recurso)
            tipo = "deadlock" if isinstance(e, DeadlockError) else "timeout"
            return QueryResult(error=str(e), tipo_error=tipo)

        for recurso in recursos:
            self.txn_manager.registrar_acceso(session_id, recurso, modo)

        try:
            with self.txn_manager.bind_current(session_id):
                if isinstance(nodo, SelectNode):
                    filas = self.ejecutar_select(nodo)
                    resultado = QueryResult(filas=filas, plan=self.plan)
                elif isinstance(nodo, InsertNode):
                    resumen = self.ejecutar_insert(nodo)
                    resultado = QueryResult(resumen=resumen, plan=self.plan)
                elif isinstance(nodo, CreateTableNode):
                    resumen = self.ejecutar_create_table(nodo, session_id)
                    resultado = QueryResult(resumen=resumen, plan=self.plan)
                elif isinstance(nodo, DropTableNode):
                    resumen = self.ejecutar_drop_table(nodo, session_id)
                    resultado = QueryResult(resumen=resumen, plan=self.plan)
                elif isinstance(nodo, CreateIndexNode):
                    resumen = self.ejecutar_create_index(nodo, session_id)
                    resultado = QueryResult(resumen=resumen, plan=self.plan)
                else:
                    resumen = self.ejecutar_delete(nodo)
                    resultado = QueryResult(resumen=resumen, plan=self.plan)
        except ERRORES_EJECUCION as e:
            resultado = QueryResult(error=str(e), tipo_error="ejecucion", plan=self.plan)
        finally:
            if not txn_estaba_activa:
                for recurso in recursos:
                    self.lock_manager.release_resource(session_id, recurso)

        txn_activa = self.txn_manager.is_active(session_id)
        txn = self.txn_manager.get_active(session_id)
        resultado.transaccion_activa = txn_activa
        resultado.xact_id = txn.xact_id if txn is not None else None
        return resultado

    # control transaccional

    def _ejecutar_begin(self, session_id: str) -> QueryResult:
        try:
            txn = self.txn_manager.begin(session_id)
        except TransactionError as e:
            return QueryResult(error=str(e), tipo_error="transaccion")
        resultado = QueryResult(
            resumen={"operacion": "BEGIN", "mensaje": f"Transaccion {txn.xact_id} iniciada"},
            plan=[f"BEGIN TRANSACTION ({txn.xact_id})"],
        )
        resultado.transaccion_activa = True
        resultado.xact_id = txn.xact_id
        return resultado

    def _ejecutar_commit(self, session_id: str) -> QueryResult:
        try:
            txn = self.txn_manager.commit(session_id)
        except TransactionError as e:
            return QueryResult(error=str(e), tipo_error="transaccion")
        resultado = QueryResult(
            resumen={"operacion": "COMMIT", "mensaje": f"Transaccion {txn.xact_id} confirmada"},
            plan=[f"END TRANSACTION ({txn.xact_id})"],
        )
        resultado.transaccion_activa = False
        resultado.xact_id = txn.xact_id
        return resultado

    def _ejecutar_rollback(self, session_id: str) -> QueryResult:
        try:
            txn = self.txn_manager.rollback(session_id)
        except TransactionError as e:
            return QueryResult(error=str(e), tipo_error="transaccion")
        self._resync_tras_rollback()
        resultado = QueryResult(
            resumen={"operacion": "ROLLBACK", "mensaje": f"Transaccion {txn.xact_id} revertida"},
            plan=[f"ROLLBACK ({txn.xact_id})"],
        )
        resultado.transaccion_activa = False
        resultado.xact_id = txn.xact_id
        return resultado

    def _resync_tras_rollback(self) -> None:
        for tabla in self.catalog.listar_tablas():
            info = self.catalog.get_table(tabla)
            objetos = [info.storage] + [indice for indice, _tipo in info.indices.values()]
            for objeto in objetos:
                reload_fn = getattr(objeto, "reload", None)
                if reload_fn is not None:
                    reload_fn()

    def _ejecutar_explain(self, nodo: ExplainNode, session_id: str) -> QueryResult:
        interna = nodo.statement
        modo = "S" if isinstance(interna, SelectNode) else "X"
        recursos = [interna.tabla]
        if isinstance(interna, SelectNode) and interna.join is not None and interna.join.tabla != interna.tabla:
            recursos.append(interna.join.tabla)
        txn_estaba_activa = self.txn_manager.is_active(session_id)

        try:
            for recurso in recursos:
                self.lock_manager.acquire(session_id, recurso, modo)
        except (DeadlockError, LockTimeoutError) as e:
            self.txn_manager.abortar_por_deadlock_o_timeout(session_id)
            self._resync_tras_rollback()
            if not txn_estaba_activa:
                for recurso in recursos:
                    self.lock_manager.release_resource(session_id, recurso)
            tipo = "deadlock" if isinstance(e, DeadlockError) else "timeout"
            return QueryResult(error=str(e), tipo_error=tipo)

        for recurso in recursos:
            self.txn_manager.registrar_acceso(session_id, recurso, modo)

        self.plan = []
        dry_run = not nodo.analyze
        error = None
        tipo_error = None
        filas = None
        filas_afectadas = 0
        inicio = time.perf_counter()
        try:
            with self.txn_manager.bind_current(session_id):
                if isinstance(interna, SelectNode):
                    filas = self.ejecutar_select(interna)
                    filas_afectadas = len(filas)
                elif isinstance(interna, InsertNode):
                    resumen = self.ejecutar_insert(interna, dry_run=dry_run)
                    filas_afectadas = resumen["filas_afectadas"]
                else:
                    resumen = self.ejecutar_delete(interna, dry_run=dry_run)
                    filas_afectadas = resumen["filas_afectadas"]
        except ERRORES_EJECUCION as e:
            error = str(e)
            tipo_error = "ejecucion"
        finally:
            if not txn_estaba_activa:
                for recurso in recursos:
                    self.lock_manager.release_resource(session_id, recurso)
        duracion_ms = (time.perf_counter() - inicio) * 1000

        plan = list(self.plan)
        etiqueta = "EXPLAIN ANALYZE" if nodo.analyze else "EXPLAIN"
        if error is None:
            if nodo.analyze:
                plan.append(f"{etiqueta}: tiempo real = {duracion_ms:.3f} ms, filas reales = {filas_afectadas}")
            else:
                que_filas = "encontradas" if isinstance(interna, SelectNode) else "que resultarian afectadas"
                plan.append(f"{etiqueta}: plan estimado, sin efectos en disco (filas {que_filas} = {filas_afectadas})")

        filas_salida = filas if (nodo.analyze and isinstance(interna, SelectNode)) else None
        resumen_salida = None
        if error is None:
            resumen_salida = {
                "operacion": etiqueta,
                "sentencia": type(interna).__name__.replace("Node", "").upper(),
                "filas_afectadas": filas_afectadas,
                "estimado": not nodo.analyze,
                "tiempo_ms": round(duracion_ms, 3) if nodo.analyze else None,
            }

        resultado = QueryResult(filas=filas_salida, resumen=resumen_salida, plan=plan,
                                 error=error, tipo_error=tipo_error)
        txn_activa = self.txn_manager.is_active(session_id)
        txn = self.txn_manager.get_active(session_id)
        resultado.transaccion_activa = txn_activa
        resultado.xact_id = txn.xact_id if txn is not None else None
        return resultado

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

    def _resolver_arg_punto(self, arg, fila: dict) -> tuple:
        if isinstance(arg, PointLiteral):
            return (arg.lat, arg.lon)
        lat, lon = fila[arg]
        return (lat, lon)

    def _resolver_arg_poligono(self, arg) -> list:
        if isinstance(arg, PolygonLiteral):
            return [(p.lat, p.lon) for p in arg.puntos]
        raise ExecutionError("se esperaba un literal POLYGON(...)")

    def _evaluar_funcion_espacial(self, funcion: FuncCall, fila: dict):
        nombre = funcion.nombre
        if nombre in ("distancia", "distancia_geo", "distancia_haversine"):
            lat1, lon1 = self._resolver_arg_punto(funcion.argumentos[0], fila)
            lat2, lon2 = self._resolver_arg_punto(funcion.argumentos[1], fila)
            return _haversine_m(lat1, lon1, lat2, lon2)
        if nombre == "distancia_euclidiana":
            lat1, lon1 = self._resolver_arg_punto(funcion.argumentos[0], fila)
            lat2, lon2 = self._resolver_arg_punto(funcion.argumentos[1], fila)
            return _euclidiana_aprox_m(lat1, lon1, lat2, lon2)
        if nombre == "dentro_de":
            lat, lon = self._resolver_arg_punto(funcion.argumentos[0], fila)
            poligono = self._resolver_arg_poligono(funcion.argumentos[1])
            return _punto_en_poligono(lat, lon, poligono)
        raise ExecutionError(f"funcion desconocida: '{nombre}'")

    def cumple_where(self, cond, fila: dict) -> bool:
        if isinstance(cond, BinaryCondition):
            lado_izq = self.cumple_where(cond.izquierda, fila)
            lado_der = self.cumple_where(cond.derecha, fila)
            if cond.operador == TokenType.AND:
                return lado_izq and lado_der
            else:
                return lado_izq or lado_der
        if isinstance(cond, SpatialCondition):
            resultado = self._evaluar_funcion_espacial(cond.funcion, fila)
            if cond.operador is None:
                return bool(resultado)
            if cond.operador == TokenType.EQ:
                return resultado == cond.valor
            if cond.operador == TokenType.NEQ:
                return resultado != cond.valor
            if cond.operador == TokenType.LT:
                return resultado < cond.valor
            if cond.operador == TokenType.LTE:
                return resultado <= cond.valor
            if cond.operador == TokenType.GT:
                return resultado > cond.valor
            if cond.operador == TokenType.GTE:
                return resultado >= cond.valor
            raise ExecutionError(f"operador desconocido: {cond.operador}")
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

    def _limite_inferior(self, tipo: DataType):
        if tipo in (DataType.SMALLINT, DataType.INT, DataType.BIGINT):
            return INT64_MIN
        if tipo in (DataType.FLOAT, DataType.DOUBLE):
            return float("-inf")
        return ""  

    def _limite_superior(self, tipo: DataType):
        if tipo in (DataType.SMALLINT, DataType.INT, DataType.BIGINT):
            return INT64_MAX
        if tipo in (DataType.FLOAT, DataType.DOUBLE):
            return float("inf")
        return "\U0010FFFF" * 64

    def _contiene_spatial(self, cond) -> bool:
        if isinstance(cond, SpatialCondition):
            return True
        if isinstance(cond, BinaryCondition):
            return self._contiene_spatial(cond.izquierda) or self._contiene_spatial(cond.derecha)
        return False

    def _extraer_rango_columna(self, cond, col_name: str, schema: Schema):
        if isinstance(cond, Condition):
            if cond.columna == col_name:
                tipo = schema.columns[schema.column_index(col_name)].type
                if cond.operador in (TokenType.GT, TokenType.GTE):
                    return (cond.valor, self._limite_superior(tipo))
                if cond.operador in (TokenType.LT, TokenType.LTE):
                    return (self._limite_inferior(tipo), cond.valor)
            return None

        if isinstance(cond, BinaryCondition) and cond.operador == TokenType.AND:
            r1 = self._extraer_rango_columna(cond.izquierda, col_name, schema)
            r2 = self._extraer_rango_columna(cond.derecha, col_name, schema)
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
        orden_ya_resuelto = False

        if nodo.join is not None:
            with tempfile.TemporaryDirectory(dir=self.tmp_dir) as tmp_join:
                filas = self.ejecutar_join(nodo, tmp_join)
            if nodo.where is not None:
                filas = [f for f in filas if self.cumple_where(nodo.where, f)]
                self.plan.append("filtro WHERE post-JOIN")
            schema = self._schema_join(nodo)
            return self._finalizar_select(nodo, filas, schema, orden_ya_resuelto)

        info = self.catalog.get_table(nodo.tabla)
        where = nodo.where
        nombres_col = [c.name for c in info.schema.columns]

        if where is None:
            usa_indice_orden = (nodo.order_by is not None
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

            rango_info = None
            for col in info.indices:
                ind, t_ind = self.catalog.get_indice(nodo.tabla, col)
                if t_ind in ("bplus", "clustered"):
                    bnds = self._extraer_rango_columna(where, col, info.schema)
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
                if self._contiene_spatial(where):
                    self.plan.append(f"escaneo secuencial completo de '{info.nombre}' ({info.tipo_storage}) "
                        "+ filtro espacial (distancia/poligono, sin indice R-Tree)")
                else:
                    self.plan.append(f"escaneo completo de '{info.nombre}' ({info.tipo_storage}) + filtro WHERE")
                filas = [f for f in self.leer_todo(info) if self.cumple_where(where, f)]
        return self._finalizar_select(nodo, filas, info.schema, orden_ya_resuelto)

    def _finalizar_select(self, nodo: SelectNode, filas, schema: Schema, orden_ya_resuelto: bool) -> list:
        with tempfile.TemporaryDirectory(dir=self.tmp_dir) as tmp:
            if nodo.group_by is not None:
                filas, schema = self.agrupar(filas, schema, nodo.group_by, tmp)
                orden_ya_resuelto = False

            if nodo.order_by is not None and not orden_ya_resuelto:
                filas = self.ordenar(filas, schema, nodo.order_by, tmp)

            if nodo.columnas == ["*"]:
                salida = list(filas)
            else:
                salida = []
                for fila in filas:
                    fila_reducida = {}
                    for col in nodo.columnas:
                        fila_reducida[col] = fila[col]
                    salida.append(fila_reducida)

            if nodo.limit is not None:
                salida = salida[:nodo.limit]
                self.plan.append(f"LIMIT {nodo.limit}")
            return salida

    def _schema_join(self, nodo: SelectNode) -> Schema:
        info1 = self.catalog.get_table(nodo.tabla)
        info2 = self.catalog.get_table(nodo.join.tabla)
        columnas = (
            [Column(f"{info1.nombre}.{c.name}", c.type, c.size) for c in info1.schema.columns] +
            [Column(f"{info2.nombre}.{c.name}", c.type, c.size) for c in info2.schema.columns]
        )
        return Schema(f"{info1.nombre}_join_{info2.nombre}", columnas)

    def _combinar_filas(self, tabla1: str, fila1: dict, tabla2: str, fila2: dict) -> dict:
        combinada = {f"{tabla1}.{k}": v for k, v in fila1.items()}
        combinada.update({f"{tabla2}.{k}": v for k, v in fila2.items()})
        return combinada

    def _buscar_por_indice(self, info: TableInfo, indice, tipo_indice: str, valor, nombres_col: list) -> list:
        if tipo_indice == "clustered":
            record = indice.search(valor)
            return [dict(zip(nombres_col, record.values))] if record is not None else []
        rids = indice.search(valor)
        filas = []
        for rid in rids:
            record = info.storage.read(rid, info.schema)
            if record is not None:
                filas.append(dict(zip(nombres_col, record.values)))
        return filas

    def ejecutar_join(self, nodo: SelectNode, tmp_dir: str) -> list:
        info1 = self.catalog.get_table(nodo.tabla)
        info2 = self.catalog.get_table(nodo.join.tabla)
        tabla1, tabla2 = info1.nombre, info2.nombre

        def lado(columna_calificada: str):
            tabla_ref, col = columna_calificada.split(".", 1)
            return col if tabla_ref == tabla1 else None, col if tabla_ref == tabla2 else None

        c1_izq, c2_izq = lado(nodo.join.columna_izquierda)
        c1_der, c2_der = lado(nodo.join.columna_derecha)
        col1 = c1_izq if c1_izq is not None else c1_der
        col2 = c2_izq if c2_izq is not None else c2_der

        nombres1 = [c.name for c in info1.schema.columns]
        nombres2 = [c.name for c in info2.schema.columns]

        if self.catalog.tiene_indice(tabla2, col2):
            indice, tipo = self.catalog.get_indice(tabla2, col2)
            self.plan.append(
                f"join anidado: escaneo de '{tabla1}' + busqueda por indice {tipo} sobre '{tabla2}.{col2}'")
            filas = []
            for fila1 in self.leer_todo(info1):
                for fila2 in self._buscar_por_indice(info2, indice, tipo, fila1[col1], nombres2):
                    filas.append(self._combinar_filas(tabla1, fila1, tabla2, fila2))
            return filas

        if self.catalog.tiene_indice(tabla1, col1):
            indice, tipo = self.catalog.get_indice(tabla1, col1)
            self.plan.append(
                f"join anidado: escaneo de '{tabla2}' + busqueda por indice {tipo} sobre '{tabla1}.{col1}'")
            filas = []
            for fila2 in self.leer_todo(info2):
                for fila1 in self._buscar_por_indice(info1, indice, tipo, fila2[col2], nombres1):
                    filas.append(self._combinar_filas(tabla1, fila1, tabla2, fila2))
            return filas

        stats = {}
        filas = list(external_hash_join(
            self.leer_todo(info1), lambda f: f[col1],
            self.leer_todo(info2), lambda f: f[col2],
            info1.schema, info2.schema,
            self.buffer_pages, tmp_dir,
            lambda fila1, fila2: self._combinar_filas(tabla1, fila1, tabla2, fila2),
            stats,
        ))
        self.plan.append(
            f"hash join externo entre '{tabla1}' y '{tabla2}' sobre '{col1}'='{col2}' "
            f"(external hashing, B={self.buffer_pages}: {stats['partitions']} particiones, "
            f"{stats['repartitions']} reparticiones)"
        )
        return filas

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
        if order_by.funcion is not None:
            clave = lambda f: self._evaluar_funcion_espacial(order_by.funcion, f)
            etiqueta = f"{order_by.funcion.nombre}(...)"
        else:
            clave = lambda f: f[order_by.columna]
            etiqueta = order_by.columna
        filas = external_sort(filas, clave, schema, self.buffer_pages,
                              tmp_dir, reverse=order_by.descendente, stats=stats)
        direccion = "DESC" if order_by.descendente else "ASC"
        self.plan.append(f"ORDER BY {etiqueta} {direccion} (external sort, B={self.buffer_pages}: "
                         f"{stats['runs']} runs, {stats['passes']} pasadas)")
        return filas

    def ejecutar_insert(self, nodo: InsertNode, dry_run: bool = False) -> dict:
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
                if self.catalog.tiene_indice(nodo.tabla, pk_col.name):
                    indice_pk, _ = self.catalog.get_indice(nodo.tabla, pk_col.name)
                    if indice_pk.search(nueva_pk):
                        raise ExecutionError(f"no se pudo insertar: clave {nueva_pk} ya existe")
                else:
                    for fila in self.leer_todo(info):
                        if fila[pk_col.name] == nueva_pk:
                            raise ExecutionError(f"no se pudo insertar: clave {nueva_pk} ya existe")

        if dry_run:
            self.plan.append(f"INSERT en '{info.nombre}' ({info.tipo_storage}) [no ejecutado]")
            return {"operacion": "INSERT", "filas_afectadas": 1}

        try:
            if info.tipo_storage == STORAGE_HEAP:
                rid = info.storage.insert(record, info.schema)
            elif info.tipo_storage == STORAGE_SEQUENTIAL:
                indice_clustered = self._indice_clustered(nodo.tabla, info.key_column)
                if indice_clustered is not None:
                    rid = indice_clustered.insert(record)
                else:
                    rid = info.storage.insert(record)
            else:
                raise ExecutionError(f"storage desconocido: {info.tipo_storage}")
            self.actualizar_indices_insert(nodo.tabla, info, record, rid)
        except ValueError as e:
            raise ExecutionError(f"no se pudo insertar: {e}")

        self.plan.append(f"INSERT en '{info.nombre}' ({info.tipo_storage})")
        self._reorganizar_si_hace_falta(nodo.tabla, info)
        return {"operacion": "INSERT", "filas_afectadas": 1}

    def necesita_reorganizar(self, tabla: str) -> bool:
        info = self.catalog.get_table(tabla)
        if info.tipo_storage != STORAGE_SEQUENTIAL:
            return False
        indice_clustered = self._indice_clustered(tabla, info.key_column)
        if indice_clustered is not None:
            return indice_clustered.needs_reorganization()
        return info.storage.needs_reorganization()

    def reorganizar_tabla(self, tabla: str) -> None:
        info = self.catalog.get_table(tabla)
        indice_clustered = self._indice_clustered(tabla, info.key_column)
        if indice_clustered is not None:
            indice_clustered.reorganize()
        else:
            info.storage.reorganize()
        self._recargar_indices(tabla, info)

    def _recargar_indices(self, tabla: str, info: TableInfo) -> None:
        # el reorganize mueve todas las filas: los RID viejos ya no valen
        secundarios = []
        for columna in info.indices:
            indice, tipo_indice = self.catalog.get_indice(tabla, columna)
            if tipo_indice != "clustered":
                secundarios.append((columna, indice, tipo_indice))
        if not secundarios:
            return

        filas = list(info.storage.scan_con_rid(info.schema))
        for columna, indice, tipo_indice in secundarios:
            idx = info.schema.column_index(columna)
            pares = [(record.values[idx], rid) for rid, record in filas]
            if tipo_indice == "bplus":
                pares.sort(key=lambda p: (p[0], p[1].page_id, p[1].slot_id))
            indice.bulk_load(pares)

    def _reorganizar_si_hace_falta(self, tabla: str, info: TableInfo) -> None:
        if not self.necesita_reorganizar(tabla):
            return
        self.reorganizar_tabla(tabla)
        self.plan.append(
            f"reorganize de '{info.nombre}' + reconstruccion de sus indices")

    def _indice_clustered(self, tabla: str, key_column: str):
        if self.catalog.tiene_indice(tabla, key_column):
            indice, tipo = self.catalog.get_indice(tabla, key_column)
            if tipo == "clustered":
                return indice
        return None

    def actualizar_indices_insert(self, tabla: str, info: TableInfo, record: Record, rid) -> None:
        for columna in info.indices:
            indice, tipo_indice = self.catalog.get_indice(tabla, columna)
            if tipo_indice == "clustered":
                continue
            idx = info.schema.column_index(columna)
            valor = record.values[idx]
            indice.insert(valor, rid)

    def ejecutar_delete(self, nodo: DeleteNode, dry_run: bool = False) -> dict:
        info = self.catalog.get_table(nodo.tabla)
        where = nodo.where
        sufijo = " [no ejecutado]" if dry_run else ""
        if where is not None:
            es_por_clave = (
                isinstance(where, Condition)
                and where.operador == TokenType.EQ
                and where.columna == info.key_column
                and info.tipo_storage == STORAGE_SEQUENTIAL
            )
            if es_por_clave:
                clave = where.valor
                self.plan.append(f"DELETE por clave '{info.key_column}={clave}' en '{info.nombre}'{sufijo}")
                if dry_run:
                    existe = info.storage.search(clave) is not None
                    return {"operacion": "DELETE", "filas_afectadas": 1 if existe else 0}
                indice_clustered = self._indice_clustered(nodo.tabla, info.key_column)
                if indice_clustered is not None:
                    borrado = indice_clustered.delete(clave)
                else:
                    borrado = info.storage.delete(clave)
                if borrado is not None:
                    rid, record = borrado
                    self.actualizar_indices_delete(nodo.tabla, info, record, rid)
                    self._reorganizar_si_hace_falta(nodo.tabla, info)
                    return {"operacion": "DELETE", "filas_afectadas": 1}
                else:
                    return {"operacion": "DELETE", "filas_afectadas": 0}

        if info.tipo_storage == STORAGE_SEQUENTIAL:
            claves = []
            for fila in self.leer_todo(info):
                if where is None or self.cumple_where(where, fila):
                    claves.append(fila[info.key_column])
            self.plan.append(f"escaneo + DELETE por clave en '{info.nombre}'{sufijo}")
            if dry_run:
                return {"operacion": "DELETE", "filas_afectadas": len(claves)}
            indice_clustered = self._indice_clustered(nodo.tabla, info.key_column)
            borradas = 0
            for clave in claves:
                if indice_clustered is not None:
                    borrado = indice_clustered.delete(clave)
                else:
                    borrado = info.storage.delete(clave)
                if borrado is not None:
                    rid, record = borrado
                    self.actualizar_indices_delete(nodo.tabla, info, record, rid)
                    borradas += 1
            self._reorganizar_si_hace_falta(nodo.tabla, info)
            return {"operacion": "DELETE", "filas_afectadas": borradas}

        if info.tipo_storage == STORAGE_HEAP:
            nombres_col = [c.name for c in info.schema.columns]
            candidatos = []
            for rid, record in info.storage.scan_con_rid(info.schema):
                fila = dict(zip(nombres_col, record.values))
                if where is None or self.cumple_where(where, fila):
                    candidatos.append((rid, record))
            self.plan.append(f"escaneo + DELETE por RID en '{info.nombre}'{sufijo}")
            if dry_run:
                return {"operacion": "DELETE", "filas_afectadas": len(candidatos)}
            for rid, record in candidatos:
                self.actualizar_indices_delete(nodo.tabla, info, record, rid)
                info.storage.delete(rid)
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

    def ejecutar_create_table(self, nodo: CreateTableNode, session_id: str) -> dict:
        if self.txn_manager.is_active(session_id):
            raise ExecutionError("CREATE TABLE no se puede ejecutar dentro de una transaccion (BEGIN...COMMIT); "
                "ejecutala como sentencia autocommit, fuera del BEGIN")
        if self.pool is None or self.data_dir is None:
            raise ExecutionError("CREATE TABLE no esta disponible: esta Conexion no tiene acceso a un BufferPool ni a un directorio de datos (pool/data_dir)")
        if self.catalog.existe_tabla(nodo.tabla):
            raise ExecutionError(f"la tabla '{nodo.tabla}' ya existe")

        columnas = []
        pk_col_name = None
        for col_def in nodo.columnas:
            tipo, tamano = resolver_tipo_columna(col_def.tipo, col_def.tamano)
            columnas.append(Column(col_def.nombre, tipo, tamano, col_def.is_pk))
            if col_def.is_pk:
                pk_col_name = col_def.nombre
        schema = Schema(nodo.tabla, columnas)
        pk_dtype = schema.columns[schema.column_index(pk_col_name)].type

        if nodo.storage == STORAGE_SEQUENTIAL:
            data_path = os.path.join(self.data_dir, f"{nodo.tabla}.bin")
            aux_path = os.path.join(self.data_dir, f"{nodo.tabla}_aux.bin")
            storage = SequentialFile(self.pool, data_path, aux_path, schema, pk_col_name)
            self.catalog.register_table(nodo.tabla, schema, storage, STORAGE_SEQUENTIAL, pk_col_name)

            idx_path = os.path.join(self.data_dir, f"{nodo.tabla}_{pk_col_name}_clustered.idx")
            indice_pk = ClusteredBPlusTree(self.pool, storage, idx_path)
            self.catalog.register_index(nodo.tabla, pk_col_name, indice_pk, INDEX_CLUSTERED)
        else:
            heap_path = os.path.join(self.data_dir, f"{nodo.tabla}.bin")
            storage = HeapFile(self.pool, heap_path)
            self.catalog.register_table(nodo.tabla, schema, storage, STORAGE_HEAP, pk_col_name)

            idx_path = os.path.join(self.data_dir, f"{nodo.tabla}_{pk_col_name}_bplus.idx")
            indice_pk = BPlusTree(self.pool, idx_path, pk_dtype, unique=True)
            self.catalog.register_index(nodo.tabla, pk_col_name, indice_pk, INDEX_BPLUS)

        self.plan.append(
            f"CREATE TABLE '{nodo.tabla}' ({nodo.storage}, {len(columnas)} columnas, "
            f"PK='{pk_col_name}' con indice automatico)")
        return {"operacion": "CREATE TABLE", "tabla": nodo.tabla, "filas_afectadas": 0}

    def ejecutar_drop_table(self, nodo: DropTableNode, session_id: str) -> dict:
        if self.txn_manager.is_active(session_id):
            raise ExecutionError("DROP TABLE no se puede ejecutar dentro de una transaccion (BEGIN...COMMIT); "
                "ejecutala como sentencia autocommit, fuera del BEGIN")
        if self.pool is None:
            raise ExecutionError("DROP TABLE no esta disponible: esta Conexion no tiene acceso a un BufferPool")
        if not self.catalog.existe_tabla(nodo.tabla):
            raise ExecutionError(f"la tabla '{nodo.tabla}' no existe")

        info = self.catalog.get_table(nodo.tabla)

        rutas = list(info.storage.file_paths())
        for indice, _tipo_indice in info.indices.values():
            for ruta in indice.file_paths():
                if ruta not in rutas:
                    rutas.append(ruta)

        for ruta in rutas:
            self.pool.close(ruta)

        borrados = 0
        for ruta in rutas:
            try:
                if os.path.exists(ruta):
                    os.remove(ruta)
                    borrados += 1
            except OSError as e:
                raise ExecutionError(f"no se pudo borrar el archivo '{ruta}' de la tabla '{nodo.tabla}': {e}")

        self.catalog.eliminar_tabla(nodo.tabla)

        self.plan.append(f"DROP TABLE '{nodo.tabla}' ({borrados} archivo(s) eliminado(s) de disco)")
        return {"operacion": "DROP TABLE", "tabla": nodo.tabla, "filas_afectadas": 0}

    def ejecutar_create_index(self, nodo: CreateIndexNode, session_id: str) -> dict:
        if self.txn_manager.is_active(session_id):
            raise ExecutionError("CREATE INDEX no se puede ejecutar dentro de una transaccion (BEGIN...COMMIT); "
                "ejecutala como sentencia autocommit, fuera del BEGIN")
        if self.pool is None or self.data_dir is None:
            raise ExecutionError("CREATE INDEX no esta disponible: esta Conexion no tiene acceso a un "
                "BufferPool ni a un directorio de datos (pool/data_dir)")
        if not self.catalog.existe_tabla(nodo.tabla):
            raise ExecutionError(f"la tabla '{nodo.tabla}' no existe")
        if self.catalog.tiene_indice(nodo.tabla, nodo.columna):
            raise ExecutionError(f"la columna '{nodo.columna}' de '{nodo.tabla}' ya tiene un indice")

        if nodo.tipo_indice == INDEX_RTREE:
            raise ExecutionError(
                f"CREATE INDEX ... USING RTREE: el indice R-Tree todavia no esta implementado "
                f"(pendiente de la parte espacial del equipo). El resto de SQL espacial "
                f"(distancia(...), dentro_de(...), ORDER BY distancia(...) LIMIT k) ya funciona "
                f"via escaneo secuencial sobre '{nodo.tabla}.{nodo.columna}', solo esta consulta "
                f"quedaria mas rapida cuando el R-Tree este listo."
            )

        info = self.catalog.get_table(nodo.tabla)
        col = info.schema.columns[info.schema.column_index(nodo.columna)]

        if nodo.tipo_indice == INDEX_HASH:
            idx_path = os.path.join(self.data_dir, f"{nodo.tabla}_{nodo.columna}_hash.idx")
            indice = ExtendibleHash(self.pool, idx_path)
        else:
            idx_path = os.path.join(self.data_dir, f"{nodo.tabla}_{nodo.columna}_bplus.idx")
            indice = BPlusTree(self.pool, idx_path, col.type, unique=False)

        pares = []
        for rid, record in info.storage.scan_con_rid(info.schema):
            valor = record.values[info.schema.column_index(nodo.columna)]
            pares.append((valor, rid))
        if nodo.tipo_indice != INDEX_HASH:
            pares.sort(key=lambda p: (p[0], p[1].page_id, p[1].slot_id))
        indice.bulk_load(pares)

        self.catalog.register_index(nodo.tabla, nodo.columna, indice, nodo.tipo_indice)

        self.plan.append(
            f"CREATE INDEX {nodo.tipo_indice} sobre '{nodo.tabla}.{nodo.columna}' "
            f"({len(pares)} entradas cargadas)")
        return {"operacion": "CREATE INDEX", "tabla": nodo.tabla, "columna": nodo.columna, "filas_afectadas": 0}