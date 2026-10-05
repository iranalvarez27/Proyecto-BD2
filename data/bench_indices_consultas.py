"""Igualdad, rango y ORDER BY con el mismo trabajo para las tres estructuras.

Cada medicion devuelve las filas completas, como el motor: el B+ agrupado lee
MAIN, el B+ no agrupado y el hash leen sus RIDs con el bitmap, y el ORDER BY
sin indice usa el external sort del motor. Antes de guardar se comprueba que
las tres estructuras devuelvan las mismas filas.

    python3 data/bench_indices_consultas.py [--sizes 1000 10000 100000]
"""
import argparse
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.bitmap import RidBitmap
from common.record import Record
from common.types import DataType
from data.generate_data import SCHEMA_ESTUDIANTES as SCHEMA, generate_estudiantes_data
from engine.buffer_pool import BufferPool
from engine.external import external_sort
from engine.file_manager import FileManager
from index.bplus_tree import BPlusTree
from index.clustered_bplus_tree import ClusteredBPlusTree
from index.extendible_hash import ExtendibleHash
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile

N_IGUALDAD = 30
N_RANGO = 10
REPS_ORDEN = 3
BUFFER_EXTERNO = 64
RANGOS = (0.01, 0.50)
NOMBRES = [c.name for c in SCHEMA.columns]


def kb(*paths):
    return sum(os.path.getsize(p) for p in paths if os.path.exists(p)) / 1024.0


def cronometrar(f):
    t0 = time.perf_counter()
    r = f()
    return time.perf_counter() - t0, r


def promedio_ms(f, args_list):
    f(args_list[0])  # calentamiento
    total = 0.0
    for a in args_list:
        dt, _ = cronometrar(lambda: f(a))
        total += dt
    return 1000.0 * total / len(args_list)


def mediana_ms(f, reps):
    f()  # calentamiento
    return 1000.0 * statistics.median(cronometrar(f)[0] for _ in range(reps))


def ids_de(filas):
    return sorted(r.values[0] for r in filas)


def leer_rids(heap, rids):
    return [r for _rid, r in heap.read_bitmap(RidBitmap.from_rids(rids), SCHEMA)]


def medir(n, seed):
    d = tempfile.mkdtemp(prefix=f"bench_idx_{n}_")
    rng = random.Random(seed)
    data = generate_estudiantes_data(n)
    pool = BufferPool(FileManager())
    res = {"n": n}

    # tablas
    heap = HeapFile(pool, f"{d}/heap.bin")
    seq = SequentialFile(pool, f"{d}/main.bin", f"{d}/aux.bin", SCHEMA, "id")
    rids = []
    for fila in data:
        rids.append(heap.insert(Record(list(fila)), SCHEMA))
        seq.insert(Record(list(fila)))

    # construccion
    dt, clustered = cronometrar(lambda: ClusteredBPlusTree(pool, seq, f"{d}/cl.idx"))
    res["construccion"] = {"bplus_agrupado": {"ms": 1000 * dt, "kb": kb(f"{d}/cl.idx")}}

    bplus = BPlusTree(pool, f"{d}/bp.idx", DataType.INT)
    dt, _ = cronometrar(lambda: [bplus.insert(f[0], rid) for f, rid in zip(data, rids)])
    res["construccion"]["bplus_no_agrupado_insert"] = {"ms": 1000 * dt, "kb": kb(f"{d}/bp.idx")}

    bplus_bulk = BPlusTree(pool, f"{d}/bpb.idx", DataType.INT)
    pares = sorted(((f[0], rid) for f, rid in zip(data, rids)),
                   key=lambda p: (p[0], p[1].page_id, p[1].slot_id))
    dt, _ = cronometrar(lambda: bplus_bulk.bulk_load(pares))
    res["construccion"]["bplus_no_agrupado_bulk"] = {"ms": 1000 * dt, "kb": kb(f"{d}/bpb.idx")}

    hash_id = ExtendibleHash(pool, f"{d}/hid.idx")
    dt, _ = cronometrar(lambda: [hash_id.insert(f[0], rid) for f, rid in zip(data, rids)])
    res["construccion"]["hash_id"] = {"ms": 1000 * dt, "kb": kb(f"{d}/hid.idx")}

    hash_car = ExtendibleHash(pool, f"{d}/hcar.idx")
    dt, _ = cronometrar(lambda: [hash_car.insert(f[2], rid) for f, rid in zip(data, rids)])
    res["construccion"]["hash_carrera"] = {"ms": 1000 * dt, "kb": kb(f"{d}/hcar.idx")}

    res["tabla_kb"] = {"heap": kb(f"{d}/heap.bin"), "sequential": kb(f"{d}/main.bin", f"{d}/aux.bin")}

    # igualdad por id (una fila) y por carrera (muchas filas, solo hash)
    claves = rng.sample([f[0] for f in data], min(N_IGUALDAD, n))
    for k in claves[:5]:
        a = clustered.search(k)
        b = leer_rids(heap, bplus.search(k))
        c = leer_rids(heap, hash_id.search(k))
        assert a.values == b[0].values == c[0].values, f"igualdad {k}"
    carreras = [rng.choice(sorted({f[2] for f in data})) for _ in range(N_IGUALDAD)]
    res["igualdad_ms"] = {
        "bplus_agrupado": promedio_ms(lambda k: clustered.search(k), claves),
        "bplus_no_agrupado": promedio_ms(lambda k: leer_rids(heap, bplus.search(k)), claves),
        "hash_id": promedio_ms(lambda k: leer_rids(heap, hash_id.search(k)), claves),
        "hash_carrera": promedio_ms(lambda c: leer_rids(heap, hash_car.search(c)), carreras),
        "filas_por_carrera": n / len({f[2] for f in data}),
    }

    # rango sobre id: el hash no lo resuelve, asi que se recorre el Heap
    res["rango_ms"] = {}
    for frac in RANGOS:
        span = max(1, int(n * frac))
        inicios = [rng.randint(1, n - span + 1) for _ in range(N_RANGO)]
        lo = inicios[0]
        a = ids_de(clustered.range_search(lo, lo + span - 1))
        b = ids_de(leer_rids(heap, bplus.range_search(lo, lo + span - 1)))
        c = ids_de(r for r in heap.scan(SCHEMA) if lo <= r.values[0] <= lo + span - 1)
        assert a == b == c and len(a) == span, f"rango {frac}"
        res["rango_ms"][f"{int(frac * 100)}%"] = {
            "filas": span,
            "bplus_agrupado": promedio_ms(lambda s: clustered.range_search(s, s + span - 1), inicios),
            "bplus_no_agrupado": promedio_ms(
                lambda s: leer_rids(heap, bplus.range_search(s, s + span - 1)), inicios),
            "heap_scan_filtro": promedio_ms(
                lambda s: [r for r in heap.scan(SCHEMA) if s <= r.values[0] <= s + span - 1], inicios),
        }

    # ORDER BY id devolviendo todas las filas
    def orden_seq():
        return list(seq.scan())

    def orden_bplus():
        return [heap.read(rid, SCHEMA) for _k, rid in bplus.scan()]

    stats_ext = {}

    def orden_heap():
        stats_ext.clear()
        filas = (dict(zip(NOMBRES, r.values)) for r in heap.scan(SCHEMA))
        return list(external_sort(filas, lambda f: f["id"], SCHEMA, BUFFER_EXTERNO, d, stats=stats_ext))

    esperado = list(range(1, n + 1))
    assert [r.values[0] for r in orden_seq()] == esperado
    assert [r.values[0] for r in orden_bplus()] == esperado
    assert [f["id"] for f in orden_heap()] == esperado
    res["orden_ms"] = {
        "sequential_lista": mediana_ms(orden_seq, REPS_ORDEN),
        "bplus_no_agrupado_hojas_y_rid": mediana_ms(orden_bplus, REPS_ORDEN),
        "heap_external_sort": mediana_ms(orden_heap, REPS_ORDEN),
        "external_sort_stats": dict(stats_ext),
    }

    pool.close_all()
    shutil.rmtree(d, ignore_errors=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 100000])
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "resultados_indices_consultas.json"))
    args = ap.parse_args()
    resultados = []
    for n in args.sizes:
        t0 = time.time()
        r = medir(n, args.seed)
        resultados.append(r)
        print(f"\n=== {n} filas ({time.time() - t0:.0f} s) ===")
        print(json.dumps({k: v for k, v in r.items() if k != "n"}, indent=2, ensure_ascii=False))
    with open(args.out, "w") as f:
        json.dump({"fecha": time.strftime("%Y-%m-%d %H:%M"), "resultados": resultados}, f, indent=2)
    print(f"\nresultados en {args.out}")


if __name__ == "__main__":
    main()
