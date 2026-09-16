import os
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import Schema, Column, DataType
from common.record import Record
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile
from index.bplus_tree import BPlusTree
from index.extendible_hash import ExtendibleHash
from index.clustered_bplus_tree import ClusteredBPlusTree
from query.catalog import (
    Catalog,
    TableInfo,
    STORAGE_HEAP,
    STORAGE_SEQUENTIAL,
    INDEX_BPLUS,
    INDEX_HASH,
    INDEX_CLUSTERED,
)
from query.conexion import Conexion
from transaction.manager import TransactionManager


class EngineAdapter:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.catalog = Catalog()
        self.txn_manager = TransactionManager()
        self.conexion = Conexion(self.catalog, self.txn_manager)
        self.clustered_trees: Dict[str, ClusteredBPlusTree] = {}
        self.init_database()

    def init_database(self):
        """Initialize tables, storage files, and indexes in the real Catalog."""
        # 1. Table 'estudiantes' -> HeapFile
        schema_estudiantes = Schema(
            table_name="estudiantes",
            columns=[
                Column(name="id", type=DataType.INT, size=4, is_pk=True),
                Column(name="nombre", type=DataType.VARCHAR, size=40, is_pk=False),
                Column(name="carrera", type=DataType.VARCHAR, size=30, is_pk=False),
                Column(name="promedio", type=DataType.FLOAT, size=4, is_pk=False),
            ],
        )
        heap_path = os.path.join(self.data_dir, "estudiantes.bin")
        heap_file = HeapFile(heap_path)
        self.catalog.register_table(
            nombre="estudiantes",
            schema=schema_estudiantes,
            storage=heap_file,
            tipo_storage=STORAGE_HEAP,
            key_column="id",
        )

        # Register B+ Tree Index on 'id'
        bplus_path = os.path.join(self.data_dir, "estudiantes_id_bplus.idx")
        bplus_idx = BPlusTree(bplus_path, DataType.INT)
        self.catalog.register_index("estudiantes", "id", bplus_idx, INDEX_BPLUS)

        # Register Extendible Hash Index on 'carrera'
        hash_path = os.path.join(self.data_dir, "estudiantes_carrera_hash.idx")
        hash_idx = ExtendibleHash(hash_path)
        self.catalog.register_index("estudiantes", "carrera", hash_idx, INDEX_HASH)

        # 2. Table 'cursos' -> SequentialFile
        schema_cursos = Schema(
            table_name="cursos",
            columns=[
                Column(name="codigo", type=DataType.INT, size=4, is_pk=True),
                Column(name="titulo", type=DataType.VARCHAR, size=50, is_pk=False),
                Column(name="creditos", type=DataType.SMALLINT, size=2, is_pk=False),
                Column(name="departamento", type=DataType.VARCHAR, size=20, is_pk=False),
            ],
        )
        seq_data = os.path.join(self.data_dir, "cursos.bin")
        seq_aux = os.path.join(self.data_dir, "cursos_aux.bin")
        seq_file = SequentialFile(seq_data, seq_aux, schema_cursos, "codigo")
        self.catalog.register_table(
            nombre="cursos",
            schema=schema_cursos,
            storage=seq_file,
            tipo_storage=STORAGE_SEQUENTIAL,
            key_column="codigo",
        )

        # Seed initial data if files are empty & synchronize indexes
        self.seed_data_if_empty()

        # Clustered B+ Tree on cursos
        clustered_path = os.path.join(self.data_dir, "cursos_clustered.idx")
        clustered_tree = ClusteredBPlusTree(seq_file, clustered_path)
        self.clustered_trees["cursos"] = clustered_tree
        self.catalog.register_index("cursos", "codigo", clustered_tree, INDEX_CLUSTERED)

    def seed_data_if_empty(self):
        """Populate initial records and synchronize index entries if files are fresh."""
        info_est = self.catalog.get_table("estudiantes")
        heap: HeapFile = info_est.storage
        if heap.page_count() == 0:
            sample_estudiantes = [
                (1, "Ana Torres", "Ciencia de la Computacion", 18.5),
                (2, "Mateo Silva", "Ingenieria de Software", 16.2),
                (3, "Lucia Morales", "Ciencia de Datos", 17.8),
                (4, "Diego Castro", "Ciencia de la Computacion", 15.4),
                (5, "Sofia Vargas", "Bioingenieria", 19.1),
                (6, "Carlos Vega", "Ciencia de la Computacion", 14.9),
                (7, "Valeria Rivas", "Ingenieria Mecatronica", 16.7),
                (8, "Jorge Herrera", "Ciencia de Datos", 17.0),
            ]
            for vals in sample_estudiantes:
                rec = Record(list(vals))
                rid = heap.insert(rec, info_est.schema)
                self.conexion.actualizar_indices_insert("estudiantes", info_est, rec, rid)
        else:
            # Check if indexes need synchronization
            bplus_idx, _ = self.catalog.get_indice("estudiantes", "id")
            hash_idx, _ = self.catalog.get_indice("estudiantes", "carrera")

            # Check if BPlus index is empty
            if getattr(bplus_idx, "_n_entries", 0) == 0:
                for rid, rec in heap.scan_con_rid(info_est.schema):
                    try:
                        bplus_idx.insert(rec.values[0], rid)
                    except Exception:
                        pass

            # Check if Hash index is empty
            sample_res = hash_idx.search("Ciencia de la Computacion")
            if len(sample_res) == 0:
                for rid, rec in heap.scan_con_rid(info_est.schema):
                    try:
                        hash_idx.insert(rec.values[2], rid)
                    except Exception:
                        pass

        info_cur = self.catalog.get_table("cursos")
        seq: SequentialFile = info_cur.storage
        if seq.page_count(0) == 0:
            sample_cursos = [
                (101, "Base de Datos 1", 4, "Computacion"),
                (102, "Algoritmos y Estructuras", 4, "Computacion"),
                (201, "Base de Datos 2", 4, "Computacion"),
                (205, "Inteligencia Artificial", 3, "Computacion"),
                (310, "Sistemas Operativos", 4, "Computacion"),
                (405, "Redes y Comunicaciones", 3, "Electronica"),
            ]
            for vals in sample_cursos:
                rec = Record(list(vals))
                seq.insert(rec)

    def get_tables_metadata(self) -> List[Dict[str, Any]]:
        result = []
        for table_name in self.catalog.listar_tablas():
            info = self.catalog.get_table(table_name)
            cols = [
                {
                    "name": col.name,
                    "type": col.type.value if hasattr(col.type, "value") else str(col.type),
                    "size": col.size,
                    "is_pk": col.is_pk,
                }
                for col in info.schema.columns
            ]

            idx_list = []
            # List all registered indexes (including clustered)
            for col_name, (idx_obj, idx_type) in info.indices.items():
                is_clustered = (idx_type == INDEX_CLUSTERED)
                idx_list.append({
                    "name": f"idx_{table_name}_{col_name}" + ("_clustered" if is_clustered else ""),
                    "type": "BTREE" if idx_type in (INDEX_BPLUS, INDEX_CLUSTERED) else "HASH",
                    "column": col_name,
                    "clustered": is_clustered,
                })

            stats = {
                "page_count": 0,
                "record_count": 0,
                "wasted_ratio": 0.0,
                "needs_reorganization": False,
            }

            if info.tipo_storage == STORAGE_HEAP:
                heap: HeapFile = info.storage
                stats["page_count"] = heap.page_count()
                stats["record_count"] = sum(1 for _ in heap.scan(info.schema))
                stats["wasted_ratio"] = 0.0
            elif info.tipo_storage == STORAGE_SEQUENTIAL:
                seq: SequentialFile = info.storage
                pages_main = seq.page_count(0)
                pages_aux = seq.page_count(1)
                stats["page_count"] = pages_main + pages_aux
                stats["record_count"] = sum(1 for _ in seq.scan())
                stats["wasted_ratio"] = round(seq.wasted_ratio(), 3)
                stats["needs_reorganization"] = seq.needs_reorganization(threshold=0.30, max_aux_records=5)

            result.append({
                "name": info.nombre,
                "storage_type": info.tipo_storage.upper(),
                "key_column": info.key_column,
                "columns": cols,
                "indexes": idx_list,
                "stats": stats,
            })
        return result

    def reorganize_table(self, table_name: str) -> Dict[str, Any]:
        if not self.catalog.existe_tabla(table_name):
            raise ValueError(f"Tabla '{table_name}' no encontrada")

        info = self.catalog.get_table(table_name)
        if info.tipo_storage != STORAGE_SEQUENTIAL:
            raise ValueError(f"La tabla '{table_name}' es {info.tipo_storage}; solo se reorganizan tablas SEQUENTIAL")

        seq: SequentialFile = info.storage
        start_time = time.time()
        seq.reorganize()

        # Rebuild clustered B+ tree if present
        if table_name in self.clustered_trees:
            self.clustered_trees[table_name]._rebuild()

        duration_ms = (time.time() - start_time) * 1000

        return {
            "success": True,
            "message": f"Tabla '{table_name}' reorganizada y su árbol B+ agrupado reconstruido con éxito.",
            "duration_ms": round(duration_ms, 2),
            "new_wasted_ratio": round(seq.wasted_ratio(), 3),
        }

    def execute_query(self, sql: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        start_time = time.time()
        sql_clean = sql.strip()
        # Cada request sin session_id explicito (curl suelto, o el cliente
        # que aun no llamo a /api/session) recibe una identidad propia y
        # unica: si dos de esas peticiones comparten un mismo id constante,
        # dejarian de excluirse mutuamente entre si (acquire() ve el lock ya
        # otorgado a "la misma sesion" y no espera), rompiendo el aislamiento
        # justo entre los clientes que mas lo necesitan.
        session_id = session_id or str(uuid.uuid4())

        if not sql_clean:
            return {
                "status": "error",
                "query": sql,
                "execution_time_ms": 0.0,
                "affected_rows": 0,
                "columns": [],
                "rows": [],
                "error": "Consulta SQL vacía.",
                "plan": None,
                "transaction": {"active": False, "xact_id": None},
            }

        # Ejecuta via Conexion real (Lexer -> Parser -> Semantico -> Ejecucion),
        # incluidos BEGIN TRANSACTION / END TRANSACTION / ROLLBACK, que ahora
        # pasan por TransactionManager/LockManager en vez de ser un mock.
        res = self.conexion.execute(sql_clean, session_id)
        duration_ms = (time.time() - start_time) * 1000
        transaction_info = {"active": res.transaccion_activa, "xact_id": res.xact_id}

        if not res.ok:
            return {
                "status": "error",
                "query": sql,
                "execution_time_ms": round(duration_ms, 2),
                "affected_rows": 0,
                "columns": [],
                "rows": [],
                "error": f"Error [{res.tipo_error.upper()}]: {res.error}",
                "plan": None,
                "transaction": transaction_info,
            }

        # Format plan steps into visual hierarchy for PlanPanel
        plan_tree = self._build_plan_tree(res.plan, sql_clean)

        # Handle SELECT result (list of dicts)
        if res.filas is not None:
            if len(res.filas) > 0:
                cols = list(res.filas[0].keys())
                rows = []
                for f in res.filas:
                    row = []
                    for c in cols:
                        v = f.get(c)
                        if isinstance(v, float):
                            v = round(v, 2)
                        row.append(v)
                    rows.append(row)
            else:
                cols = ["Resultado"]
                rows = []

            return {
                "status": "success",
                "query": sql,
                "execution_time_ms": round(duration_ms, 2),
                "affected_rows": len(rows),
                "columns": cols,
                "rows": rows,
                "error": None,
                "plan": plan_tree,
                "transaction": transaction_info,
            }

        # Handle BEGIN / COMMIT / ROLLBACK (mensaje) y INSERT / DELETE (resumen)
        if res.resumen is not None:
            if "mensaje" in res.resumen:
                return {
                    "status": "success",
                    "query": sql,
                    "execution_time_ms": round(duration_ms, 2),
                    "affected_rows": 0,
                    "columns": ["Mensaje"],
                    "rows": [[res.resumen["mensaje"]]],
                    "error": None,
                    "plan": plan_tree,
                    "transaction": transaction_info,
                }
            operacion = res.resumen.get("operacion", "Operación")
            filas_afectadas = res.resumen.get("filas_afectadas", 1)
            return {
                "status": "success",
                "query": sql,
                "execution_time_ms": round(duration_ms, 2),
                "affected_rows": filas_afectadas,
                "columns": ["Operación", "Filas Afectadas"],
                "rows": [[operacion, filas_afectadas]],
                "error": None,
                "plan": plan_tree,
                "transaction": transaction_info,
            }

        return {
            "status": "success",
            "query": sql,
            "execution_time_ms": round(duration_ms, 2),
            "affected_rows": 0,
            "columns": ["Estado"],
            "rows": [["Consulta ejecutada sin retorno de datos"]],
            "error": None,
            "plan": plan_tree,
            "transaction": transaction_info,
        }

    def _build_plan_tree(self, plan_steps: List[str], sql: str) -> Dict[str, Any]:
        """Convert linear query plan steps from Conexion into a visual hierarchical tree."""
        if not plan_steps:
            return {
                "node_type": "QueryPlan",
                "query": sql,
                "cost": 1.0,
                "rows_estimated": 1,
                "children": [],
            }

        nodes = []
        for step in plan_steps:
            step_lower = step.lower()
            if "begin transaction" in step_lower or "end transaction" in step_lower or "rollback" in step_lower:
                nodes.append({
                    "node_type": "TransactionControl",
                    "method": step,
                    "cost": 0.0,
                    "rows_estimated": 0,
                    "children": [],
                })
            elif "agrupado" in step_lower and "no agrupado" not in step_lower:
                nodes.append({
                    "node_type": "IndexScan (B+ Tree Agrupado)",
                    "method": step,
                    "cost": 1.10,
                    "rows_estimated": 5,
                    "children": [],
                })
            elif "no agrupado" in step_lower:
                nodes.append({
                    "node_type": "IndexScan (B+ Tree No Agrupado)",
                    "method": step,
                    "cost": 1.25,
                    "rows_estimated": 5,
                    "children": [],
                })
            elif "bplus" in step_lower:
                nodes.append({
                    "node_type": "IndexScan (B+ Tree)",
                    "method": step,
                    "cost": 1.20,
                    "rows_estimated": 5,
                    "children": [],
                })
            elif "hash" in step_lower:
                nodes.append({
                    "node_type": "IndexScan (Extendible Hash)",
                    "method": step,
                    "cost": 1.05,
                    "rows_estimated": 5,
                    "children": [],
                })
            elif "binaria" in step_lower:
                nodes.append({
                    "node_type": "SequentialBinarySearch",
                    "method": step,
                    "cost": 1.25,
                    "rows_estimated": 1,
                    "children": [],
                })
            elif "secuencial ordenada" in step_lower:
                nodes.append({
                    "node_type": "SequentialScan (Ordenado por PK)",
                    "method": step,
                    "cost": 1.10,
                    "rows_estimated": 10,
                    "children": [],
                })
            elif "escaneo" in step_lower or "heap" in step_lower:
                nodes.append({
                    "node_type": "FullTableScan",
                    "method": step,
                    "cost": 2.50,
                    "rows_estimated": 10,
                    "children": [],
                })
            elif "order by" in step_lower:
                nodes.append({
                    "node_type": "Sort (ORDER BY)",
                    "method": step,
                    "cost": 1.80,
                    "rows_estimated": 10,
                    "children": [],
                })
            elif "group by" in step_lower:
                nodes.append({
                    "node_type": "Aggregate (GROUP BY)",
                    "method": step,
                    "cost": 1.50,
                    "rows_estimated": 5,
                    "children": [],
                })
            elif "insert" in step_lower:
                nodes.append({
                    "node_type": "InsertTuple",
                    "method": step,
                    "cost": 1.0,
                    "rows_estimated": 1,
                    "children": [],
                })
            elif "delete" in step_lower:
                nodes.append({
                    "node_type": "DeleteTuple",
                    "method": step,
                    "cost": 1.5,
                    "rows_estimated": 1,
                    "children": [],
                })
            else:
                nodes.append({
                    "node_type": "ExecutionStep",
                    "method": step,
                    "cost": 1.0,
                    "rows_estimated": 5,
                    "children": [],
                })

        # Nest nodes into an execution tree: leaf (bottom) to root (top)
        curr = nodes[0]
        for next_node in nodes[1:]:
            next_node["children"] = [curr]
            next_node["cost"] = round(next_node["cost"] + curr["cost"], 2)
            curr = next_node

        # Wrap with a Projection root node
        root = {
            "node_type": "Projection",
            "relation": "Resultado",
            "cost": round(curr["cost"] + 0.1, 2),
            "rows_estimated": curr.get("rows_estimated", 5),
            "children": [curr],
        }
        return root

    def explain_query(self, sql: str) -> Dict[str, Any]:
        """Runs the query to extract the real execution plan."""
        res = self.conexion.execute(sql.strip())
        if not res.ok:
            return {
                "query": sql,
                "root_node": {
                    "node_type": "ErrorInQuery",
                    "error": f"{res.tipo_error}: {res.error}",
                    "cost": 0.0,
                    "rows_estimated": 0,
                    "children": [],
                },
            }
        return {
            "query": sql,
            "root_node": self._build_plan_tree(res.plan, sql),
        }
