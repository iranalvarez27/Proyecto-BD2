import os
import sys
import time
import json
import random
import argparse
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.types import DataType
from common.record import Record
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile
from index.bplus_tree import BPlusTree
from index.extendible_hash import ExtendibleHash
from index.clustered_bplus_tree import ClusteredBPlusTree
from data.generate_data import SCHEMA_ESTUDIANTES, generate_estudiantes_data

DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def _tmp(suffix: str) -> str:
    return tempfile.mktemp(suffix=suffix)


def _size_kb(*paths: str) -> float:
    return sum(os.path.getsize(p) for p in paths if os.path.exists(p)) / 1024.0


def _cleanup(*paths: str) -> None:
    for p in paths:
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def bench_heap_vs_sequential(n: int, n_queries: int, seed: int = 7) -> dict:
    data = generate_estudiantes_data(n)
    rng = random.Random(seed)
    muestra = rng.sample([row[0] for row in data], min(n_queries, n))

    heap_path = _tmp(f"_rel_heap_{n}.bin")
    pool = BufferPool(FileManager())
    heap = HeapFile(pool, heap_path)
    t0 = time.perf_counter()
    for row in data:
        heap.insert(Record(list(row)), SCHEMA_ESTUDIANTES)
    t_insert_heap = time.perf_counter() - t0

    t0 = time.perf_counter()
    for key in muestra:
        for rec in heap.scan(SCHEMA_ESTUDIANTES):
            if rec.values[0] == key:
                break
    t_search_heap = (time.perf_counter() - t0) / len(muestra)
    size_heap = _size_kb(heap_path)
    pool.close_all()
    _cleanup(heap_path)

    main_path = _tmp(f"_rel_main_{n}.bin")
    aux_path = _tmp(f"_rel_aux_{n}.bin")
    pool2 = BufferPool(FileManager())
    seq = SequentialFile(pool2, main_path, aux_path, SCHEMA_ESTUDIANTES, "id")
    t0 = time.perf_counter()
    for row in data:
        seq.insert(Record(list(row)))
    t_insert_seq = time.perf_counter() - t0

    t0 = time.perf_counter()
    for key in muestra:
        seq.search(key)
    t_search_seq = (time.perf_counter() - t0) / len(muestra)
    size_seq = _size_kb(main_path, aux_path)

    rng2 = random.Random(seed + 1)
    a_borrar = rng2.sample([row[0] for row in data], max(1, n // 5))
    for key in a_borrar:
        seq.delete(key)
    wasted_before = seq.wasted_ratio()
    t0 = time.perf_counter()
    seq.reorganize()
    t_reorg = time.perf_counter() - t0
    wasted_after = seq.wasted_ratio()

    pool2.close_all()
    _cleanup(main_path, aux_path)

    return {
        "n": n,
        "heap": {
            "insert_time_ms": t_insert_heap * 1000.0,
            "search_avg_us": t_search_heap * 1e6,
            "disk_size_kb": size_heap,
        },
        "sequential": {
            "insert_time_ms": t_insert_seq * 1000.0,
            "search_avg_us": t_search_seq * 1e6,
            "disk_size_kb": size_seq,
            "reorganize_time_ms": t_reorg * 1000.0,
            "wasted_before": wasted_before,
            "wasted_after": wasted_after,
        },
    }


def bench_indices(n: int, n_queries: int, seed: int = 11) -> dict:
    data = generate_estudiantes_data(n)
    rng = random.Random(seed)
    ids_muestra = rng.sample([row[0] for row in data], min(n_queries, n))
    carreras_unicas = sorted({row[2] for row in data})
    carreras_muestra = [rng.choice(carreras_unicas) for _ in range(len(ids_muestra))]
    span = max(1, n // 100)
    n_rangos = min(20, len(ids_muestra))

    heap_path = _tmp(f"_idx_heap_{n}.bin")
    bplus_path = _tmp(f"_idx_bplus_{n}.idx")
    hash_path = _tmp(f"_idx_hash_{n}.idx")
    pool = BufferPool(FileManager())
    heap = HeapFile(pool, heap_path)
    bplus = BPlusTree(pool, bplus_path, DataType.INT)
    eh = ExtendibleHash(pool, hash_path)

    rids = []
    for row in data:
        rid = heap.insert(Record(list(row)), SCHEMA_ESTUDIANTES)
        rids.append((row[0], row[2], rid))

    t0 = time.perf_counter()
    for student_id, _carrera, rid in rids:
        bplus.insert(student_id, rid)
    t_build_bplus = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _student_id, carrera, rid in rids:
        eh.insert(carrera, rid)
    t_build_hash = time.perf_counter() - t0

    size_bplus = _size_kb(bplus_path)
    size_hash = _size_kb(hash_path)

    t0 = time.perf_counter()
    for key in ids_muestra:
        bplus.search(key)
    t_eq_bplus = (time.perf_counter() - t0) / len(ids_muestra)

    t0 = time.perf_counter()
    for carrera in carreras_muestra:
        eh.search(carrera)
    t_eq_hash = (time.perf_counter() - t0) / len(carreras_muestra)

    t0 = time.perf_counter()
    for key in ids_muestra[:n_rangos]:
        bplus.range_search(key, key + span)
    t_range_bplus = (time.perf_counter() - t0) / n_rangos

    t0 = time.perf_counter()
    list(bplus.scan())
    t_order_bplus = time.perf_counter() - t0

    t0 = time.perf_counter()
    sorted(row[2] for row in data)
    t_order_hash = time.perf_counter() - t0

    pool.close_all()
    _cleanup(heap_path, bplus_path, hash_path)

    main_path = _tmp(f"_idx_main_{n}.bin")
    aux_path = _tmp(f"_idx_aux_{n}.bin")
    cl_path = _tmp(f"_idx_cl_{n}.idx")
    pool2 = BufferPool(FileManager())
    seq = SequentialFile(pool2, main_path, aux_path, SCHEMA_ESTUDIANTES, "id")
    for row in data:
        seq.insert(Record(list(row)))

    t0 = time.perf_counter()
    clustered = ClusteredBPlusTree(pool2, seq, cl_path)
    t_build_clustered = time.perf_counter() - t0
    size_clustered = _size_kb(cl_path)

    t0 = time.perf_counter()
    for key in ids_muestra:
        clustered.search(key)
    t_eq_clustered = (time.perf_counter() - t0) / len(ids_muestra)

    t0 = time.perf_counter()
    for key in ids_muestra[:n_rangos]:
        clustered.range_search(key, key + span)
    t_range_clustered = (time.perf_counter() - t0) / n_rangos

    t0 = time.perf_counter()
    list(seq.scan())  # fisicamente ordenado: no hace falta ordenar
    t_order_clustered = time.perf_counter() - t0

    pool2.close_all()
    _cleanup(main_path, aux_path, cl_path)

    return {
        "n": n,
        "bplus_unclustered": {
            "build_ms": t_build_bplus * 1000.0, "size_kb": size_bplus,
            "eq_us": t_eq_bplus * 1e6, "range_us": t_range_bplus * 1e6,
            "order_ms": t_order_bplus * 1000.0,
        },
        "hash": {
            "build_ms": t_build_hash * 1000.0, "size_kb": size_hash,
            "eq_us": t_eq_hash * 1e6, "range_us": None,
            "order_ms": t_order_hash * 1000.0,
        },
        "bplus_clustered": {
            "build_ms": t_build_clustered * 1000.0, "size_kb": size_clustered,
            "eq_us": t_eq_clustered * 1e6, "range_us": t_range_clustered * 1e6,
            "order_ms": t_order_clustered * 1000.0,
        },
    }


def run(sizes: list, n_queries: int) -> dict:
    resultados = {
        "metadata": {"sizes": sizes, "n_queries": n_queries, "date": time.strftime("%Y-%m-%d %H:%M:%S")},
        "heap_vs_sequential": {},
        "indices": {},
    }
    for n in sizes:
        label = f"{n // 1000}K" if n >= 1000 else str(n)
        print(f"\n=== {label} registros ===")
        print("  [A] Heap File vs Archivo Secuencial...")
        res_a = bench_heap_vs_sequential(n, n_queries)
        print(f"      Heap:       insert {res_a['heap']['insert_time_ms']:.2f} ms | "
              f"busqueda PK {res_a['heap']['search_avg_us']:.1f} us/op | {res_a['heap']['disk_size_kb']:.1f} KB")
        print(f"      Secuencial: insert {res_a['sequential']['insert_time_ms']:.2f} ms | "
              f"busqueda PK {res_a['sequential']['search_avg_us']:.1f} us/op | "
              f"{res_a['sequential']['disk_size_kb']:.1f} KB | "
              f"reorg {res_a['sequential']['reorganize_time_ms']:.2f} ms "
              f"({res_a['sequential']['wasted_before'] * 100:.1f}% -> {res_a['sequential']['wasted_after'] * 100:.1f}%)")
        resultados["heap_vs_sequential"][str(n)] = res_a

        print("  [B] B+ no agrupado vs B+ agrupado vs Hash Dinamico...")
        res_b = bench_indices(n, n_queries)
        for clave, nombre in (("bplus_unclustered", "B+ no agrupado"),
                              ("bplus_clustered", "B+ agrupado"),
                              ("hash", "Hash dinamico")):
            d = res_b[clave]
            rango_txt = f"{d['range_us']:.1f} us/op" if d["range_us"] is not None else "N/A"
            print(f"      {nombre:<16} build {d['build_ms']:.2f} ms | {d['size_kb']:.1f} KB | "
                  f"igualdad {d['eq_us']:.1f} us/op | rango {rango_txt} | orden {d['order_ms']:.2f} ms")
        resultados["indices"][str(n)] = res_b

    return resultados


def save_results(resultados: dict, json_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"\n  Resultados JSON guardados en: {json_path}")


COLOR_HEAP = "#2a78d6"
COLOR_SEQUENTIAL = "#eb6834"
COLOR_BPLUS_UNCL = "#2a78d6"
COLOR_BPLUS_CL = "#eb6834"
COLOR_HASH = "#1baf7a"

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"


def _configurar_estilo(plt):
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "axes.edgecolor": BASELINE, "axes.labelcolor": INK_SECONDARY,
        "axes.titlecolor": INK_PRIMARY, "text.color": INK_PRIMARY,
        "xtick.color": INK_MUTED, "ytick.color": INK_MUTED,
        "grid.color": GRIDLINE, "font.size": 10, "font.family": "sans-serif",
        "axes.grid": True, "grid.linewidth": 0.6, "axes.linewidth": 0.8,
        "legend.frameon": False,
    })


def _style_axes(ax):
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(BASELINE)
    ax.tick_params(length=0)
    ax.grid(axis="y", alpha=0.7)
    ax.set_axisbelow(True)


def _grouped_bars(ax, categorias, series: dict, colors: dict, ylabel, log=False):
    n_series = len(series)
    width = 0.8 / max(n_series, 1)
    x = range(len(categorias))
    for i, (nombre, valores) in enumerate(series.items()):
        offset = (i - (n_series - 1) / 2) * width
        xs = [xi + offset for xi in x]
        ax.bar(xs, valores, width=width * 0.92, label=nombre, color=colors[nombre], edgecolor="none")
    ax.set_xticks(list(x))
    ax.set_xticklabels(categorias)
    ax.set_ylabel(ylabel)
    if log:
        ax.set_yscale("log")
    _style_axes(ax)


def _etiquetas(sizes):
    return [f"{n // 1000}K" if n >= 1000 else str(n) for n in sizes]


def grafica_heap_vs_sequential(resultados: dict, out_dir: str) -> str:
    import matplotlib.pyplot as plt
    sizes = resultados["metadata"]["sizes"]
    cats = _etiquetas(sizes)
    data = resultados["heap_vs_sequential"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    colors = {"Heap File": COLOR_HEAP, "Archivo Secuencial": COLOR_SEQUENTIAL}

    series_insert = {
        "Heap File": [data[str(n)]["heap"]["insert_time_ms"] for n in sizes],
        "Archivo Secuencial": [data[str(n)]["sequential"]["insert_time_ms"] for n in sizes],
    }
    _grouped_bars(axes[0], cats, series_insert, colors, "Tiempo de insercion (ms, log)", log=True)
    axes[0].set_title("Insercion masiva")
    axes[0].set_xlabel("Tamano del dataset")
    axes[0].legend(loc="upper left")

    series_search = {
        "Heap File": [data[str(n)]["heap"]["search_avg_us"] for n in sizes],
        "Archivo Secuencial": [data[str(n)]["sequential"]["search_avg_us"] for n in sizes],
    }
    _grouped_bars(axes[1], cats, series_search, colors, "us / busqueda (log)", log=True)
    axes[1].set_title("Busqueda por clave primaria")
    axes[1].set_xlabel("Tamano del dataset")
    axes[1].legend(loc="upper left")

    fig.suptitle("Heap File vs Archivo Secuencial Paginado", y=1.03, color=INK_PRIMARY)
    fig.tight_layout()
    path = os.path.join(out_dir, "06_rel_insercion_busqueda.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def grafica_espacio_reorg(resultados: dict, out_dir: str) -> str:
    import matplotlib.pyplot as plt
    sizes = resultados["metadata"]["sizes"]
    cats = _etiquetas(sizes)
    data = resultados["heap_vs_sequential"]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    colors = {"Heap File": COLOR_HEAP, "Archivo Secuencial": COLOR_SEQUENTIAL}

    series_size = {
        "Heap File": [data[str(n)]["heap"]["disk_size_kb"] for n in sizes],
        "Archivo Secuencial": [data[str(n)]["sequential"]["disk_size_kb"] for n in sizes],
    }
    _grouped_bars(axes[0], cats, series_size, colors, "Espacio en disco (KB, log)", log=True)
    axes[0].set_title("Espacio en disco")
    axes[0].set_xlabel("Tamano del dataset")
    axes[0].legend(loc="upper left")

    valores_reorg = [data[str(n)]["sequential"]["reorganize_time_ms"] for n in sizes]
    axes[1].bar(cats, valores_reorg, color=COLOR_SEQUENTIAL, width=0.5)
    axes[1].set_ylabel("Tiempo de reorganizacion (ms)")
    axes[1].set_title("Reorganizacion (Archivo Secuencial, ~20% de borrados)")
    axes[1].set_xlabel("Tamano del dataset")
    _style_axes(axes[1])

    fig.suptitle("Espacio en disco y costo de reorganizacion", y=1.03, color=INK_PRIMARY)
    fig.tight_layout()
    path = os.path.join(out_dir, "07_rel_espacio_reorganizacion.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def grafica_indices_construccion(resultados: dict, out_dir: str) -> str:
    import matplotlib.pyplot as plt
    sizes = resultados["metadata"]["sizes"]
    cats = _etiquetas(sizes)
    data = resultados["indices"]
    nombres = {"bplus_unclustered": "B+ no agrupado", "bplus_clustered": "B+ agrupado", "hash": "Hash dinamico"}
    colors = {"B+ no agrupado": COLOR_BPLUS_UNCL, "B+ agrupado": COLOR_BPLUS_CL, "Hash dinamico": COLOR_HASH}

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    series_build = {nombres[k]: [data[str(n)][k]["build_ms"] for n in sizes] for k in nombres}
    _grouped_bars(axes[0], cats, series_build, colors, "Tiempo de construccion (ms, log)", log=True)
    axes[0].set_title("Construccion del indice")
    axes[0].set_xlabel("Tamano del dataset")
    axes[0].legend(loc="upper left", fontsize=8)

    series_size = {nombres[k]: [data[str(n)][k]["size_kb"] for n in sizes] for k in nombres}
    _grouped_bars(axes[1], cats, series_size, colors, "Espacio adicional (KB, log)", log=True)
    axes[1].set_title("Espacio adicional del indice")
    axes[1].set_xlabel("Tamano del dataset")
    axes[1].legend(loc="upper left", fontsize=8)

    fig.suptitle("B+ no agrupado vs B+ agrupado vs Hash Dinamico: construccion", y=1.03, color=INK_PRIMARY)
    fig.tight_layout()
    path = os.path.join(out_dir, "08_indices_construccion_espacio.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def grafica_indices_consultas(resultados: dict, out_dir: str) -> str:
    import matplotlib.pyplot as plt
    sizes = resultados["metadata"]["sizes"]
    cats = _etiquetas(sizes)
    data = resultados["indices"]
    nombres = {"bplus_unclustered": "B+ no agrupado", "bplus_clustered": "B+ agrupado", "hash": "Hash dinamico"}
    colors = {"B+ no agrupado": COLOR_BPLUS_UNCL, "B+ agrupado": COLOR_BPLUS_CL, "Hash dinamico": COLOR_HASH}

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.4))

    series_eq = {nombres[k]: [data[str(n)][k]["eq_us"] for n in sizes] for k in nombres}
    _grouped_bars(axes[0], cats, series_eq, colors, "us / consulta (log)", log=True)
    axes[0].set_title("Igualdad exacta")
    axes[0].set_xlabel("Tamano del dataset")

    series_range = {nombres[k]: [data[str(n)][k]["range_us"] for n in sizes]
                    for k in ("bplus_unclustered", "bplus_clustered")}
    _grouped_bars(axes[1], cats, series_range,
                 {nombres[k]: colors[nombres[k]] for k in ("bplus_unclustered", "bplus_clustered")},
                 "us / consulta (log)", log=True)
    axes[1].set_title("Busqueda por rango (Hash: no soportado)")
    axes[1].set_xlabel("Tamano del dataset")

    series_order = {nombres[k]: [data[str(n)][k]["order_ms"] for n in sizes] for k in nombres}
    _grouped_bars(axes[2], cats, series_order, colors, "ms (log)", log=True)
    axes[2].set_title("Recorrido ordenado")
    axes[2].set_xlabel("Tamano del dataset")

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.08))
    fig.suptitle("B+ no agrupado vs B+ agrupado vs Hash Dinamico: consultas", y=1.16, color=INK_PRIMARY)
    fig.tight_layout()
    path = os.path.join(out_dir, "09_indices_consultas.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def generar_todas_las_graficas(resultados: dict, out_dir: str = None) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _configurar_estilo(plt)

    if out_dir is None:
        out_dir = os.path.join(DATA_DIR, "charts")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n  -> Generando graficas en: {out_dir}")
    rutas = {
        "insercion_busqueda": grafica_heap_vs_sequential(resultados, out_dir),
        "espacio_reorg": grafica_espacio_reorg(resultados, out_dir),
        "indices_construccion": grafica_indices_construccion(resultados, out_dir),
        "indices_consultas": grafica_indices_consultas(resultados, out_dir),
    }
    for nombre, ruta in rutas.items():
        print(f"     {nombre}: {ruta}")
    return rutas


def main():
    parser = argparse.ArgumentParser(description="Benchmark y graficas de la Parte 1 (Seccion 2.1.6)")
    parser.add_argument("--sizes", nargs="+", default=["1k", "10k", "100k"],
                        help="Tamanos de dataset a evaluar (ej. 1k 10k 100k)")
    parser.add_argument("--queries", type=int, default=30,
                        help="Numero de consultas aleatorias por prueba para promediar (default: 30)")
    parser.add_argument("--plot", action="store_true", help="Generar graficas PNG y tabla resumen al terminar")
    args = parser.parse_args()

    size_map = {"1k": 1_000, "10k": 10_000, "100k": 100_000}
    sizes = []
    for s in args.sizes:
        s_lower = s.lower()
        if s_lower in size_map:
            sizes.append(size_map[s_lower])
        else:
            try:
                sizes.append(int(s))
            except ValueError:
                print(f"Tamano invalido: '{s}'. Use '1k', '10k', '100k' o enteros.")
                sys.exit(1)
    sizes.sort()

    t0 = time.perf_counter()
    resultados = run(sizes, args.queries)
    t_total = time.perf_counter() - t0

    json_path = os.path.join(DATA_DIR, "relational_benchmark_results.json")
    save_results(resultados, json_path)

    print(f"\n{'=' * 55}")
    print(f"  BENCHMARK FINALIZADO EN {t_total:.2f} SEGUNDOS")
    print(f"{'=' * 55}")

    if args.plot:
        generar_todas_las_graficas(resultados)


if __name__ == "__main__":
    main()
