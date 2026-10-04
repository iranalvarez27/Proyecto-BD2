"""
=============================================================================
  BENCHMARK DE INSERCIONES Y ELIMINACIONES FRECUENTES – Sección 2.1.6
  Proyecto BD2 – Minigestor Multimodal
=============================================================================
  Evalúa el rendimiento de los tres índices relacionales ante una carga mixta
  (churn / mutaciones frecuentes):
    1. B+ Tree No Agrupado (sobre HeapFile)
    2. Extendible Hash (sobre HeapFile)
    3. B+ Tree Agrupado (sobre SequentialFile)

  Metodología:
    - Estado inicial: Tabla pre-poblada con N = 10,000 registros.
    - Carga de churn: M = 1,000 operaciones intercaladas (500 inserts + 500 deletes).
    - Métricas: Latencia total de inserción, latencia total de eliminación,
                tiempo por operación (us), throughput (ops/s) y estado físico.
=============================================================================
"""

import os
import sys
import time
import random
import tempfile
from typing import Dict, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.types import DataType, RID
from common.record import Record
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile, MAIN_FILE, AUX_FILE
from index.bplus_tree import BPlusTree
from index.extendible_hash import ExtendibleHash
from index.clustered_bplus_tree import ClusteredBPlusTree
from data.generate_data import (
    SCHEMA_ESTUDIANTES,
    SCHEMA_CURSOS,
    generate_estudiantes_data,
    generate_cursos_data
)


def run_churn_benchmark(n_base: int = 10_000, n_ops: int = 1_000) -> Dict[str, Any]:
    print("=============================================================================")
    print(f"  BENCHMARK DE MUTACIONES FRECUENTES (N_BASE={n_base:,}, OPS={n_ops:,})")
    print("=============================================================================\n")

    n_inserts = n_ops // 2
    n_deletes = n_ops // 2

    # Generar población inicial con claves pares para permitir inserciones intermedias (odd keys)
    rng = random.Random(42)
    even_student_ids = [i * 2 for i in range(1, n_base + 1)]
    even_cursos_ids = [100 + i * 2 for i in range(1, n_base + 1)]

    # Claves para eliminar (subconjunto aleatorio de los pares iniciales)
    keys_to_delete_students = rng.sample(even_student_ids, n_deletes)
    keys_to_delete_cursos = rng.sample(even_cursos_ids, n_deletes)

    # Nuevas tuplas para insertar (claves impares que caen dispersas en medio de los datos)
    new_student_ids = [i * 2 - 1 for i in range(1, n_inserts + 1)]
    new_students_data = [
        (new_id, f"Alumno Churn {new_id}", "Computacion", 15.5)
        for new_id in new_student_ids
    ]
    new_cursos_ids = [100 + (i * 2 - 1) for i in range(1, n_inserts + 1)]
    new_cursos_data = [
        (c_id, f"Curso Churn {c_id}", 4, "Computacion")
        for c_id in new_cursos_ids
    ]

    # Secuencia intercalada (I, D, I, D, ...)
    ops_sequence = []
    for i in range(n_inserts):
        ops_sequence.append(("insert", i))
        ops_sequence.append(("delete", i))

    results = {}

    # -------------------------------------------------------------------------
    # 1. B+ TREE NO AGRUPADO (sobre HeapFile)
    # -------------------------------------------------------------------------
    print("1. Evaluando B+ Tree No Agrupado...")
    tmp_heap = tempfile.mktemp(suffix="_bench_heap.bin")
    tmp_bplus = tempfile.mktemp(suffix="_bench_bplus.idx")
    pool = BufferPool(FileManager())
    heap = HeapFile(pool, tmp_heap)
    bplus = BPlusTree(pool, tmp_bplus, DataType.INT, unique=True)

    # Poblar base inicial (claves pares)
    init_students_data = [
        (sid, f"Alumno Base {sid}", "Computacion", 15.0)
        for sid in even_student_ids
    ]
    id_to_rid = {}
    for row in init_students_data:
        rid = heap.insert(Record(list(row)), SCHEMA_ESTUDIANTES)
        bplus.insert(row[0], rid)
        id_to_rid[row[0]] = rid

    # Medir churn intercalado
    t_insert_total = 0.0
    t_delete_total = 0.0
    t_start = time.perf_counter()

    for op, idx in ops_sequence:
        if op == "insert":
            row = new_students_data[idx]
            t0 = time.perf_counter()
            rid = heap.insert(Record(list(row)), SCHEMA_ESTUDIANTES)
            bplus.insert(row[0], rid)
            t_insert_total += (time.perf_counter() - t0)
            id_to_rid[row[0]] = rid
        else:
            del_key = keys_to_delete_students[idx]
            rid = id_to_rid.get(del_key)
            t0 = time.perf_counter()
            if rid:
                bplus.delete(del_key, rid)
                heap.delete(rid)
            t_delete_total += (time.perf_counter() - t0)

    t_total_bplus = time.perf_counter() - t_start
    size_bplus_kb = os.path.getsize(tmp_bplus) / 1024.0

    pool.close_all()
    for p in (tmp_heap, tmp_bplus):
        if os.path.exists(p): os.remove(p)

    results["bplus_unclustered"] = {
        "insert_time_ms": t_insert_total * 1000.0,
        "delete_time_ms": t_delete_total * 1000.0,
        "total_time_ms": t_total_bplus * 1000.0,
        "avg_insert_us": (t_insert_total * 1e6) / n_inserts,
        "avg_delete_us": (t_delete_total * 1e6) / n_deletes,
        "throughput_ops_sec": n_ops / t_total_bplus,
        "final_size_kb": size_bplus_kb
    }
    print(f"   ✓ Inserciones ({n_inserts}): {t_insert_total*1000:.2f} ms (promedio: {(t_insert_total*1e6)/n_inserts:.1f} µs/op)")
    print(f"   ✓ Eliminaciones ({n_deletes}): {t_delete_total*1000:.2f} ms (promedio: {(t_delete_total*1e6)/n_deletes:.1f} µs/op)")
    print(f"   ✓ Throughput: {n_ops/t_total_bplus:.0f} ops/s | Tamaño: {size_bplus_kb:.1f} KB\n")

    # -------------------------------------------------------------------------
    # 2. EXTENDIBLE HASH (sobre HeapFile)
    # -------------------------------------------------------------------------
    print("2. Evaluando Extendible Hash...")
    tmp_heap = tempfile.mktemp(suffix="_bench_heap.bin")
    tmp_hash = tempfile.mktemp(suffix="_bench_hash.idx")
    pool = BufferPool(FileManager())
    heap = HeapFile(pool, tmp_heap)
    eh = ExtendibleHash(pool, tmp_hash)

    id_to_rid = {}
    for row in init_students_data:
        rid = heap.insert(Record(list(row)), SCHEMA_ESTUDIANTES)
        eh.insert(row[0], rid)
        id_to_rid[row[0]] = rid

    t_insert_total = 0.0
    t_delete_total = 0.0
    t_start = time.perf_counter()

    for op, idx in ops_sequence:
        if op == "insert":
            row = new_students_data[idx]
            t0 = time.perf_counter()
            rid = heap.insert(Record(list(row)), SCHEMA_ESTUDIANTES)
            eh.insert(row[0], rid)
            t_insert_total += (time.perf_counter() - t0)
            id_to_rid[row[0]] = rid
        else:
            del_key = keys_to_delete_students[idx]
            rid = id_to_rid.get(del_key)
            t0 = time.perf_counter()
            if rid:
                eh.delete(del_key, rid)
                heap.delete(rid)
            t_delete_total += (time.perf_counter() - t0)

    t_total_hash = time.perf_counter() - t_start
    size_hash_kb = os.path.getsize(tmp_hash) / 1024.0

    pool.close_all()
    for p in (tmp_heap, tmp_hash):
        if os.path.exists(p): os.remove(p)

    results["extendible_hash"] = {
        "insert_time_ms": t_insert_total * 1000.0,
        "delete_time_ms": t_delete_total * 1000.0,
        "total_time_ms": t_total_hash * 1000.0,
        "avg_insert_us": (t_insert_total * 1e6) / n_inserts,
        "avg_delete_us": (t_delete_total * 1e6) / n_deletes,
        "throughput_ops_sec": n_ops / t_total_hash,
        "final_size_kb": size_hash_kb
    }
    print(f"   ✓ Inserciones ({n_inserts}): {t_insert_total*1000:.2f} ms (promedio: {(t_insert_total*1e6)/n_inserts:.1f} µs/op)")
    print(f"   ✓ Eliminaciones ({n_deletes}): {t_delete_total*1000:.2f} ms (promedio: {(t_delete_total*1e6)/n_deletes:.1f} µs/op)")
    print(f"   ✓ Throughput: {n_ops/t_total_hash:.0f} ops/s | Tamaño: {size_hash_kb:.1f} KB\n")

    # -------------------------------------------------------------------------
    # 3. B+ TREE AGRUPADO (sobre SequentialFile)
    # -------------------------------------------------------------------------
    print("3. Evaluando B+ Tree Agrupado (SequentialFile)...")
    tmp_main = tempfile.mktemp(suffix="_bench_main.bin")
    tmp_aux = tempfile.mktemp(suffix="_bench_aux.bin")
    tmp_cl = tempfile.mktemp(suffix="_bench_cl.idx")
    pool = BufferPool(FileManager())
    seq = SequentialFile(pool, tmp_main, tmp_aux, SCHEMA_CURSOS, "codigo")

    init_cursos_data = [
        (cid, f"Curso Base {cid}", 4, "Computacion")
        for cid in even_cursos_ids
    ]
    for row in init_cursos_data:
        seq.insert(Record(list(row)))

    clustered = ClusteredBPlusTree(pool, seq, tmp_cl)

    t_insert_total = 0.0
    t_delete_total = 0.0
    t_start = time.perf_counter()

    for op, idx in ops_sequence:
        if op == "insert":
            row = new_cursos_data[idx]
            t0 = time.perf_counter()
            clustered.insert(Record(list(row)))
            t_insert_total += (time.perf_counter() - t0)
        else:
            del_key = keys_to_delete_cursos[idx]
            t0 = time.perf_counter()
            clustered.delete(del_key)
            t_delete_total += (time.perf_counter() - t0)

    t_total_cl = time.perf_counter() - t_start
    size_cl_kb = os.path.getsize(tmp_cl) / 1024.0
    aux_pages = seq.page_count(AUX_FILE)
    del_ratio = seq.deleted_ratio()
    needs_reorg = clustered.needs_reorganization()

    pool.close_all()
    for p in (tmp_main, tmp_aux, tmp_cl):
        if os.path.exists(p): os.remove(p)

    results["bplus_clustered"] = {
        "insert_time_ms": t_insert_total * 1000.0,
        "delete_time_ms": t_delete_total * 1000.0,
        "total_time_ms": t_total_cl * 1000.0,
        "avg_insert_us": (t_insert_total * 1e6) / n_inserts,
        "avg_delete_us": (t_delete_total * 1e6) / n_deletes,
        "throughput_ops_sec": n_ops / t_total_cl,
        "final_size_kb": size_cl_kb,
        "aux_pages": aux_pages,
        "deleted_ratio": del_ratio,
        "needs_reorganization": needs_reorg
    }
    print(f"   ✓ Inserciones ({n_inserts}): {t_insert_total*1000:.2f} ms (promedio: {(t_insert_total*1e6)/n_inserts:.1f} µs/op)")
    print(f"   ✓ Eliminaciones ({n_deletes}): {t_delete_total*1000:.2f} ms (promedio: {(t_delete_total*1e6)/n_deletes:.1f} µs/op)")
    print(f"   ✓ Throughput: {n_ops/t_total_cl:.0f} ops/s | Tamaño: {size_cl_kb:.1f} KB")
    print(f"   ✓ Estado físico: AUX={aux_pages} páginas, Borrados={del_ratio*100:.1f}%, Reorganización requerida={needs_reorg}\n")

    return results


def plot_churn_results(results: Dict[str, Any]):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        output_dir = os.path.join(PROJECT_ROOT, "data", "charts")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, "11_churn_mutaciones.png")

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        indices = ["Hash extendible", "B+ no agrupado", "B+ agrupado"]
        keys = ["extendible_hash", "bplus_unclustered", "bplus_clustered"]

        ins_latencies = [results[k]["avg_insert_us"] for k in keys]
        del_latencies = [results[k]["avg_delete_us"] for k in keys]
        throughputs = [results[k]["throughput_ops_sec"] for k in keys]

        colors_idx = ["#ef4444", "#f59e0b", "#10b981"]

        # Panel 1: Latencias (Inserción vs Eliminación)
        x = np.arange(len(indices))
        w = 0.35
        rects1 = ax1.bar(x - w/2, ins_latencies, w, label="Inserción", color="#3b82f6", edgecolor="white", alpha=0.9)
        rects2 = ax1.bar(x + w/2, del_latencies, w, label="Eliminación", color="#ec4899", edgecolor="white", alpha=0.9)

        ax1.set_title("Latencia por Operación en Churn (µs)", fontsize=11, fontweight="bold", pad=10)
        ax1.set_ylabel("Tiempo promedio (µs / operación)", fontsize=10)
        ax1.set_xticks(x)
        ax1.set_xticklabels(indices, fontsize=9)
        ax1.legend(fontsize=9)
        ax1.grid(axis="y", linestyle="--", alpha=0.3)
        ax1.spines["top"].set_visible(False)
        ax1.spines["right"].set_visible(False)

        for rect in rects1:
            h = rect.get_height()
            ax1.annotate(f"{h:.1f}", xy=(rect.get_x() + rect.get_width() / 2, h),
                         xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8)
        for rect in rects2:
            h = rect.get_height()
            ax1.annotate(f"{h:.1f}", xy=(rect.get_x() + rect.get_width() / 2, h),
                         xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8)

        # Panel 2: Throughput
        rects3 = ax2.bar(indices, throughputs, color=colors_idx, width=0.5, edgecolor="white")
        ax2.set_title("Throughput en Carga Mixta (ops/s)", fontsize=11, fontweight="bold", pad=10)
        ax2.set_ylabel("Operaciones por segundo", fontsize=10)
        ax2.tick_params(axis="x", labelsize=9)
        ax2.grid(axis="y", linestyle="--", alpha=0.3)
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)

        for rect in rects3:
            h = rect.get_height()
            ax2.annotate(f"{h:,.0f} ops/s", xy=(rect.get_x() + rect.get_width() / 2, h),
                         xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8, fontweight="bold")

        fig.suptitle("Rendimiento ante Mutaciones Frecuentes (N=10,000 | 500 Inserts / 500 Deletes)", fontsize=13, fontweight="bold", y=1.02)
        plt.tight_layout()
        fig.savefig(out_path, dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"   ✓ Gráfico generado exitosamente: {out_path}\n")
    except Exception as e:
        print(f"   Advertencia: No se pudo generar el gráfico: {e}\n")


if __name__ == "__main__":
    res = run_churn_benchmark()
    plot_churn_results(res)
