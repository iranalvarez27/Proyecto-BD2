import os
import sys
import json
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

COLOR_SECUENCIAL = "#2a78d6"
COLOR_RTREE = "#eb6834"
COLOR_POSTGIS = "#1baf7a"

TECNICAS = [
    ("secuencial", "Busqueda Secuencial", COLOR_SECUENCIAL),
    ("rtree", "R-Tree Propio", COLOR_RTREE),
    ("postgis_gist", "PostgreSQL GiST", COLOR_POSTGIS),
]

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK_SECONDARY,
    "axes.titlecolor": INK_PRIMARY,
    "text.color": INK_PRIMARY,
    "xtick.color": INK_MUTED,
    "ytick.color": INK_MUTED,
    "grid.color": GRIDLINE,
    "font.size": 10,
    "font.family": "sans-serif",
    "axes.grid": True,
    "grid.linewidth": 0.6,
    "axes.linewidth": 0.8,
    "legend.frameon": False,
})


def _cargar(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _tamanos_ordenados(data: dict) -> list:
    return sorted(data.keys(), key=lambda s: int(s))


def _etiqueta(n_str: str, data: dict) -> str:
    return data[n_str].get("label", n_str)


def _style_axes(ax) -> None:
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(BASELINE)
    ax.tick_params(length=0)
    ax.grid(axis="y", alpha=0.7)
    ax.set_axisbelow(True)


def _grouped_bars(ax, categorias: list, series: dict, colors: dict, ylabel: str, log=False):
    n_series = len(series)
    n_cat = len(categorias)
    width = 0.8 / max(n_series, 1)
    x = range(n_cat)
    for i, (nombre, valores) in enumerate(series.items()):
        offset = (i - (n_series - 1) / 2) * width
        xs = [xi + offset for xi in x]
        ax.bar(xs, valores, width=width * 0.92, label=nombre, color=colors[nombre],
               edgecolor="none")
    ax.set_xticks(list(x))
    ax.set_xticklabels(categorias)
    ax.set_ylabel(ylabel)
    if log:
        ax.set_yscale("log")
    _style_axes(ax)


def grafica_construccion_indices(data: dict, out_dir: str) -> str:
    sizes = _tamanos_ordenados(data)
    categorias = [_etiqueta(n, data) for n in sizes]
    series = {
        "R-Tree Propio": [data[n]["rtree"].get("build_time_ms", 0) for n in sizes],
        "PostgreSQL GiST": [data[n]["postgis_gist"].get("build_time_ms", 0) for n in sizes],
    }
    colors = {"R-Tree Propio": COLOR_RTREE, "PostgreSQL GiST": COLOR_POSTGIS}
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    _grouped_bars(ax, categorias, series, colors, "Tiempo de construccion (ms, log)", log=True)
    ax.set_title("Construccion del indice: R-Tree vs GiST")
    ax.set_xlabel("Tamano del dataset")
    ax.legend(loc="upper left")
    fig.tight_layout()
    path = os.path.join(out_dir, "01_spatial_construccion_indices.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def grafica_espacio_disco(data: dict, out_dir: str) -> str:
    sizes = _tamanos_ordenados(data)
    categorias = [_etiqueta(n, data) for n in sizes]
    series = {
        "R-Tree Propio": [data[n]["rtree"].get("index_size_kb", 0) for n in sizes],
        "PostgreSQL GiST": [data[n]["postgis_gist"].get("index_size_kb", 0) for n in sizes],
    }
    colors = {"R-Tree Propio": COLOR_RTREE, "PostgreSQL GiST": COLOR_POSTGIS}
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    _grouped_bars(ax, categorias, series, colors, "Espacio en disco (KB, log)", log=True)
    ax.set_title("Espacio adicional del indice: R-Tree vs GiST")
    ax.set_xlabel("Tamano del dataset")
    ax.legend(loc="upper left")
    fig.tight_layout()
    path = os.path.join(out_dir, "02_spatial_espacio_disco.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _faceted_latency(data: dict, out_dir: str, campo: str, claves: list,
                     etiquetas_x: list, titulo: str, archivo: str) -> str:
    sizes = _tamanos_ordenados(data)
    fig, axes = plt.subplots(1, len(sizes), figsize=(4.4 * len(sizes), 4.2), sharey=False)
    if len(sizes) == 1:
        axes = [axes]
    for ax, n in zip(axes, sizes):
        series = {}
        for tecnica_key, nombre, _color in TECNICAS:
            valores = []
            bloque = data[n].get(tecnica_key, {}).get(campo, {})
            for clave in claves:
                valor = bloque.get(str(clave), bloque.get(clave, 0))
                valores.append(valor)
            series[nombre] = valores
        colors = {nombre: color for _k, nombre, color in TECNICAS}
        _grouped_bars(ax, etiquetas_x, series, colors, "ms / consulta (log)", log=True)
        ax.set_title(_etiqueta(n, data))
    axes[0].set_ylabel("ms / consulta (log)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(TECNICAS), bbox_to_anchor=(0.5, 1.04))
    fig.suptitle(titulo, y=1.12, color=INK_PRIMARY)
    fig.tight_layout()
    path = os.path.join(out_dir, archivo)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def grafica_radio(data: dict, out_dir: str) -> str:
    radios = data[next(iter(data))].get("metadata_radios") or [1000, 5000, 10000]
    etiquetas = [f"{int(r) // 1000} km" for r in radios]
    return _faceted_latency(data, out_dir, "radius_ms", radios, etiquetas,
                            "Latencia por radio de busqueda (1, 5, 10 km)",
                            "03_spatial_radio_1k_5k_10k.png")


def grafica_knn(data: dict, out_dir: str) -> str:
    ks = [10, 50, 100]
    etiquetas = [f"k={k}" for k in ks]
    return _faceted_latency(data, out_dir, "knn_ms", ks, etiquetas,
                            "Latencia k-NN (k = 10, 50, 100)",
                            "04_spatial_knn_10_50_100.png")


def grafica_escalamiento(data: dict, out_dir: str) -> str:
    sizes = _tamanos_ordenados(data)
    ns = [data[n]["n"] for n in sizes]
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    for tecnica_key, nombre, color in TECNICAS:
        valores = []
        for n in sizes:
            bloque = data[n].get(tecnica_key, {}).get("radius_ms", {})
            valores.append(bloque.get("5000", bloque.get(5000, 0)))
        ax.plot(ns, valores, marker="o", markersize=5, linewidth=2, color=color, label=nombre)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Tamano del dataset (N, log)")
    ax.set_ylabel("ms / consulta a radio 5 km (log)")
    ax.set_title("Escalabilidad: tiempo de consulta vs. tamano del dataset")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _p: f"{int(v):,}"))
    _style_axes(ax)
    ax.legend(loc="upper left")
    fig.tight_layout()
    path = os.path.join(out_dir, "05_spatial_escalamiento.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def generar_todas_las_graficas(json_path: str, out_dir: str = None) -> dict:
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(json_path)), "charts")
    os.makedirs(out_dir, exist_ok=True)

    resultados = _cargar(json_path)
    data = resultados["data"]
    if not data:
        raise ValueError(f"'{json_path}' no tiene resultados (data vacio)")

    print(f"\n  -> Generando graficas en: {out_dir}")
    rutas = {
        "construccion": grafica_construccion_indices(data, out_dir),
        "espacio": grafica_espacio_disco(data, out_dir),
        "radio": grafica_radio(data, out_dir),
        "knn": grafica_knn(data, out_dir),
        "escalamiento": grafica_escalamiento(data, out_dir),
    }
    for nombre, ruta in rutas.items():
        print(f"     {nombre}: {ruta}")

    return rutas


def main():
    parser = argparse.ArgumentParser(description="Genera las graficas de la comparacion espacial (2.2.4)")
    parser.add_argument("--json", default=os.path.join(PROJECT_ROOT, "data", "spatial_benchmark_results.json"),
                        help="Ruta al JSON generado por bench_spatial.py")
    parser.add_argument("--out", default=None, help="Carpeta de salida para las graficas (default: data/charts)")
    args = parser.parse_args()

    if not os.path.exists(args.json):
        print(f"No se encontro '{args.json}'. Corre primero: python3 data/bench_spatial.py")
        sys.exit(1)

    generar_todas_las_graficas(args.json, args.out)


if __name__ == "__main__":
    main()
