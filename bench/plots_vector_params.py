"""Recall@10 vs tiempo por indice, desde un csv de vector_params.py."""
import argparse
import csv
import math
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import yaml

BENCH = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(BENCH, "results", "vector_params.csv")

INDICES = (("HNSW", "efSearch", "#2a78d6", "o"), ("IVF", "nprobe", "#eb6834", "s"))
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
    "grid.linewidth": 0.6,
    "axes.linewidth": 0.8,
    "legend.frameon": False,
})


def _tamano(n: int) -> str:
    return f"{n // 1000}k" if n % 1000 == 0 else str(n)


def cargar(ruta):
    """{metrica: {n: {indice: [filas ordenadas por valor]}}}"""
    datos = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with open(ruta, newline="") as f:
        for fila in csv.DictReader(f):
            fila["n"] = int(fila["n"])
            fila["recall"] = float(fila["recall"])
            fila["tiempo_ms"] = float(fila["tiempo_ms"])
            fila["valor"] = int(fila["valor"]) if fila["valor"] else None
            datos[fila["metrica"]][fila["n"]][fila["indice"]].append(fila)
    for por_n in datos.values():
        for por_indice in por_n.values():
            for filas in por_indice.values():
                filas.sort(key=lambda f: f["valor"] or 0)
    return datos


def _ms(v, _pos=None) -> str:
    return f"{v:g}"


def _estilo(ax):
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(True, which="major", alpha=0.7)
    ax.set_axisbelow(True)


def _eje_tiempo(ax, tiempos):
    decadas = math.log10(max(tiempos) / min(tiempos))
    subs = (1, 2, 3, 5) if decadas < 1.2 else (1, 2, 5) if decadas < 1.8 else (1, 3)
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(mticker.LogLocator(base=10, subs=subs))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_ms))
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())


def graficar(metrica, por_n, objetivo, salida):
    tamanos = sorted(por_n)
    fig, ejes = plt.subplots(1, len(tamanos), figsize=(3.6 * len(tamanos), 3.4), sharey=True, squeeze=False)
    for ax, n in zip(ejes[0], tamanos):
        _estilo(ax)
        _eje_tiempo(ax, [f["tiempo_ms"] for filas in por_n[n].values() for f in filas])
        ax.set_title(f"N = {_tamano(n)}", fontsize=10)
        ax.axhline(objetivo, color=INK_MUTED, linewidth=1, linestyle="--", zorder=1,
                   label=f"objetivo {objetivo}")
        exacto = por_n[n].get("exacto")
        if exacto:
            ax.axvline(exacto[0]["tiempo_ms"], color=INK_MUTED, linewidth=1, linestyle=":", zorder=1,
                       label="k-NN exacto")
        for nombre, parametro, color, marcador in INDICES:
            filas = por_n[n].get(nombre, [])
            if not filas:
                continue
            x = [f["tiempo_ms"] for f in filas]
            y = [f["recall"] for f in filas]
            ax.plot(x, y, color=color, linewidth=2, marker=marcador, markersize=5,
                    markeredgecolor=SURFACE, markeredgewidth=1, label=nombre, zorder=3)
            elegido = next((f for f in filas if f["recall"] >= objetivo), None)
            if elegido:
                abajo = nombre == "HNSW"
                ax.annotate(f"{parametro} {elegido['valor']}", (elegido["tiempo_ms"], elegido["recall"]),
                            xytext=(6, -6 if abajo else 6), textcoords="offset points",
                            ha="left", va="top" if abajo else "bottom",
                            fontsize=8, color=INK_SECONDARY)
        ax.set_xlabel("tiempo por consulta (ms)")
    ejes[0][0].set_ylabel("Recall@10")
    ejes[0][0].set_ylim(top=1.06)
    asas, etiquetas = ejes[0][0].get_legend_handles_labels()
    fig.legend(asas, etiquetas, loc="upper center", ncol=len(asas), bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(salida, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entrada", default=ENTRADA)
    ap.add_argument("--salida", default=os.path.join(BENCH, "results"))
    args = ap.parse_args()
    objetivo = yaml.safe_load(open(os.path.join(BENCH, "config.yaml")))["vector"]["recall_objetivo"]
    os.makedirs(args.salida, exist_ok=True)
    nombre = os.path.splitext(os.path.basename(args.entrada))[0]
    for metrica, por_n in cargar(args.entrada).items():
        ruta = os.path.join(args.salida, f"{nombre}_{metrica}.png")
        graficar(metrica, por_n, objetivo, ruta)
        print(ruta)


if __name__ == "__main__":
    main()
