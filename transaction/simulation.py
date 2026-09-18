"""Demo obligatoria con hilos: transacciones simultaneas, carrera de PK y
deadlock real, con y sin el LockManager.

Uso:
    python -m transaction.simulation --threads 8 --mode locked
    python -m transaction.simulation --threads 8 --mode raceless
    python -m transaction.simulation --threads 8 --mode locked --xacts 3 --seed 42
    python -m transaction.simulation --scenario deadlock
"""
import argparse
import os
import random
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.types import Schema, Column, DataType
from common.record import Record
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile
from index.bplus_tree import BPlusTree
from index.extendible_hash import ExtendibleHash
from index.clustered_bplus_tree import ClusteredBPlusTree
from query.catalog import (
    Catalog, STORAGE_HEAP, STORAGE_SEQUENTIAL, INDEX_BPLUS, INDEX_HASH, INDEX_CLUSTERED,
)
from query.conexion import Conexion
from transaction.manager import TransactionManager
from transaction.serializability import construir_grafo_precedencia


# --------------------------------------------------------------- entorno

def construir_entorno(data_dir: str, pool: BufferPool) -> Catalog:
    os.makedirs(data_dir, exist_ok=True)
    catalog = Catalog()

    schema_estudiantes = Schema(table_name="estudiantes", columns=[
        Column(name="id", type=DataType.INT, size=4, is_pk=True),
        Column(name="nombre", type=DataType.VARCHAR, size=30, is_pk=False),
        Column(name="carrera", type=DataType.VARCHAR, size=30, is_pk=False),
        Column(name="promedio", type=DataType.FLOAT, size=4, is_pk=False),
    ])
    heap = HeapFile(pool, os.path.join(data_dir, "estudiantes.bin"))
    catalog.register_table("estudiantes", schema_estudiantes, heap, STORAGE_HEAP, "id")
    bplus = BPlusTree(pool, os.path.join(data_dir, "estudiantes_id.idx"), DataType.INT)
    catalog.register_index("estudiantes", "id", bplus, INDEX_BPLUS)
    hash_idx = ExtendibleHash(pool, os.path.join(data_dir, "estudiantes_carrera.idx"))
    catalog.register_index("estudiantes", "carrera", hash_idx, INDEX_HASH)

    schema_cursos = Schema(table_name="cursos", columns=[
        Column(name="codigo", type=DataType.INT, size=4, is_pk=True),
        Column(name="titulo", type=DataType.VARCHAR, size=30, is_pk=False),
        Column(name="creditos", type=DataType.SMALLINT, size=2, is_pk=False),
        Column(name="departamento", type=DataType.VARCHAR, size=20, is_pk=False),
    ])
    seq = SequentialFile(
        pool,
        os.path.join(data_dir, "cursos.bin"),
        os.path.join(data_dir, "cursos_aux.bin"),
        schema_cursos,
        "codigo",
    )
    catalog.register_table("cursos", schema_cursos, seq, STORAGE_SEQUENTIAL, "codigo")
    clustered = ClusteredBPlusTree(pool, seq, os.path.join(data_dir, "cursos_clustered.idx"))
    catalog.register_index("cursos", "codigo", clustered, INDEX_CLUSTERED)

    for i in range(1, 6):
        rec = Record([i, f"Base{i}", "Base", 15.0])
        rid = heap.insert(rec, schema_estudiantes)
        bplus.insert(i, rid)
        hash_idx.insert("Base", rid)
    for codigo in (1, 2, 3):
        seq.insert(Record([codigo, f"CursoBase{codigo}", 4, "Base"]))

    return catalog


# ------------------------------------------------------------ invariantes

def verificar_pk_unicas(catalog: Catalog) -> list:
    info = catalog.get_table("estudiantes")
    conteo: dict = {}
    for record in info.storage.scan(info.schema):
        pk = record.values[0]
        conteo[pk] = conteo.get(pk, 0) + 1
    return [(pk, n) for pk, n in conteo.items() if n > 1]


def verificar_indices_coherentes(catalog: Catalog) -> int:
    info = catalog.get_table("estudiantes")
    bplus, _ = catalog.get_indice("estudiantes", "id")
    idx_pk = info.schema.column_index("id")
    incoherentes = 0
    for clave, rid in bplus.scan():
        record = info.storage.read(rid, info.schema)
        if record is None or record.values[idx_pk] != clave:
            incoherentes += 1
    return incoherentes


# --------------------------------------------------------- INSERT sin lock

def raceless_insert(catalog: Catalog, tabla: str, valores: list, delay_s: float):
    info = catalog.get_table(tabla)
    record = Record(valores)
    pk_col = next(c for c in info.schema.columns if c.is_pk)
    idx_pk = info.schema.column_index(pk_col.name)
    nueva_pk = record.values[idx_pk]

    existe = any(r.values[idx_pk] == nueva_pk for r in info.storage.scan(info.schema))
    time.sleep(delay_s)  # ensancha a proposito la ventana entre check y write
    if existe:
        raise ValueError(f"clave {nueva_pk} ya existe")

    rid = info.storage.insert(record, info.schema)
    for columna in info.indices:
        indice, tipo = catalog.get_indice(tabla, columna)
        if tipo == "clustered":
            continue
        valor = record.values[info.schema.column_index(columna)]
        indice.insert(valor, rid)
    return rid


# --------------------------------------------------------------- escenarios

def escenario_carrera(catalog, conexion, n_threads, n_claves, modo, delay_ms, seed):
    random.seed(seed)
    barrera = threading.Barrier(n_threads)
    resultados = []
    candado = threading.Lock()

    def log(msg):
        with candado:
            print(msg)

    def trabajo(i):
        pk = 500 + (i % n_claves)
        session_id = f"race-{i}"
        barrera.wait()
        try:
            if modo == "locked":
                b = conexion.execute("BEGIN TRANSACTION;", session_id=session_id)
                xact_id = b.xact_id
                log(f"  [hilo-{i}] {xact_id} BEGIN TRANSACTION")
                r = conexion.execute(
                    f"INSERT INTO estudiantes VALUES ({pk}, 'Hilo{i}', 'Concurrencia', 10.0);",
                    session_id=session_id,
                )
                if r.ok:
                    conexion.execute("END TRANSACTION;", session_id=session_id)
                    log(f"  [hilo-{i}] {xact_id} INSERT id={pk} ok -> END TRANSACTION (commit)")
                    ok, detalle = True, f"insertado ({xact_id})"
                else:
                    conexion.execute("ROLLBACK;", session_id=session_id)
                    log(f"  [hilo-{i}] {xact_id} INSERT id={pk} fallo ({r.error}) -> ROLLBACK")
                    ok, detalle = False, f"{r.error} ({xact_id})"
            else:
                raceless_insert(
                    catalog, "estudiantes",
                    [pk, f"Hilo{i}", "Concurrencia", 10.0],
                    delay_ms / 1000,
                )
                ok, detalle = True, "insertado"
        except (ValueError, Exception) as e:
            ok, detalle = False, str(e)
        with candado:
            resultados.append((i, pk, ok, detalle))

    hilos = [threading.Thread(target=trabajo, args=(i,)) for i in range(n_threads)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    print()
    resultados.sort(key=lambda t: t[0])
    for i, pk, ok, detalle in resultados:
        estado = "OK" if ok else "rechazado"
        print(f"  [hilo-{i}] INSERT estudiantes(id={pk}) -> {estado} ({detalle})")
    return resultados


def escenario_deadlock(conexion, delay_ms):
    barrera = threading.Barrier(2)
    resultado = {}

    def t1():
        conexion.execute("BEGIN TRANSACTION;", session_id="D1")
        conexion.execute("INSERT INTO estudiantes VALUES (600,'d1','d1',1.0);", session_id="D1")
        print("  [hilo-1] T(D1) BEGIN TRANSACTION; adquiere X en 'estudiantes'")
        barrera.wait()
        time.sleep(delay_ms / 1000)
        print("  [hilo-1] T(D1) esperando X en 'cursos' ...")
        r = conexion.execute("INSERT INTO cursos VALUES (700,'d1c',1,'d');", session_id="D1")
        if r.ok:
            conexion.execute("COMMIT;", session_id="D1")
            print("  [hilo-1] T(D1) adquiere X en 'cursos' -> END TRANSACTION (commit)")
            resultado["D1"] = "commit"
        else:
            print(f"  [hilo-1] T(D1) {r.tipo_error}: {r.error}")
            resultado["D1"] = r.tipo_error

    def t2():
        conexion.execute("BEGIN TRANSACTION;", session_id="D2")
        conexion.execute("INSERT INTO cursos VALUES (701,'d2c',1,'d');", session_id="D2")
        print("  [hilo-2] T(D2) BEGIN TRANSACTION; adquiere X en 'cursos'")
        barrera.wait()
        time.sleep(delay_ms / 1000)
        print("  [hilo-2] T(D2) esperando X en 'estudiantes' ...")
        r = conexion.execute("INSERT INTO estudiantes VALUES (601,'d2','d2',1.0);", session_id="D2")
        if r.ok:
            conexion.execute("COMMIT;", session_id="D2")
            print("  [hilo-2] T(D2) adquiere X en 'estudiantes' -> END TRANSACTION (commit)")
            resultado["D2"] = "commit"
        else:
            print(f"  [hilo-2] T(D2) {r.tipo_error}: {r.error}")
            resultado["D2"] = r.tipo_error

    h1 = threading.Thread(target=t1)
    h2 = threading.Thread(target=t2)
    h1.start()
    h2.start()
    h1.join()
    h2.join()
    return resultado


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Demo de concurrencia con hilos (BD2 - Transacciones)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--mode", choices=["locked", "raceless"], default="locked")
    ap.add_argument("--xacts", type=int, default=3, help="claves distintas en pugna en el escenario 'race'")
    ap.add_argument("--scenario", choices=["race", "deadlock"], default="race")
    ap.add_argument("--delay-ms", type=float, default=50.0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    data_dir = os.path.join("data", f"sim_{os.getpid()}_{int(time.time())}")
    pool = BufferPool(FileManager())
    catalog = construir_entorno(data_dir, pool)
    txn_manager = TransactionManager(pool=pool)
    conexion = Conexion(catalog, txn_manager)

    print(f"== Simulacion (modo={args.mode}, escenario={args.scenario}, hilos={args.threads}, seed={args.seed}) ==")

    try:
        if args.scenario == "deadlock":
            resultado = escenario_deadlock(conexion, args.delay_ms)
            print()
            print("[resultado] D1:", resultado.get("D1"))
            print("[resultado] D2:", resultado.get("D2"))
            hubo_deadlock = "deadlock" in (resultado.get("D1"), resultado.get("D2"))
            print("[verificacion] deadlock detectado y victima abortada:", "SI" if hubo_deadlock else "NO")
        else:
            resultados = escenario_carrera(
                catalog, conexion, args.threads, args.xacts, args.mode, args.delay_ms, args.seed
            )

        duplicados = verificar_pk_unicas(catalog)
        huerfanos = verificar_indices_coherentes(catalog)

        print()
        if duplicados:
            print(f"[verificacion] INCONSISTENCIA: PK duplicadas en 'estudiantes' -> {duplicados}")
        else:
            print("[verificacion] PK unicas OK en 'estudiantes'")
        if huerfanos:
            print(f"[verificacion] INCONSISTENCIA: {huerfanos} entradas de indice incoherentes (huerfanas o con 'lost update')")
        else:
            print("[verificacion] 0 entradas de indice incoherentes")

        if args.scenario == "race":
            info = catalog.get_table("estudiantes")
            claves_presentes = {r.values[0] for r in info.storage.scan(info.schema)}
            claves_intentadas = {pk for _i, pk, ok, _d in resultados if ok}
            faltantes = claves_intentadas - claves_presentes
            if faltantes:
                print(f"[verificacion] INCONSISTENCIA: {len(faltantes)} INSERT reportados como exitosos "
                      f"pero la fila no esta en disco (lost update) -> claves {sorted(faltantes)}")
            else:
                print("[verificacion] todo INSERT reportado como exitoso persistio en disco")

        if args.mode == "locked":
            grafo = construir_grafo_precedencia(txn_manager.lock_manager.historia)
            ciclo = grafo.encontrar_ciclo()
            if ciclo is None:
                orden = grafo.orden_serial() or []
                print("[verificacion] Schedule SERIALIZABLE (grafo de precedencia aciclico)")
                if orden:
                    print("[verificacion] orden serial equivalente:", " -> ".join(orden))
            else:
                print(f"[verificacion] Schedule NO VALIDO: ciclo {' -> '.join(ciclo)}")
        else:
            print("[verificacion] modo raceless: sin locks no hay protocolo que ordene los accesos;")
            print("                la evidencia de la carrera son las inconsistencias reportadas arriba.")
    finally:
        pool.close_all()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
