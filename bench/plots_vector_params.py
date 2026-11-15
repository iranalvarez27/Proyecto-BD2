import argparse
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import yaml

BENCH = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(BENCH, "results", "vector_params.csv")

INDICES = (("HNSW", "efSearch"), ("IVF", "nprobe"))
# un tono por tamano, del mas claro al mas oscuro
TAMANOS = {1000: ("#9DB4CC", "o"), 10000: ("#3F6C8F", "s"), 100000: ("#1E3A5F", "D")}
GRIS = "#6C7480"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["CMU Serif", "Latin Modern Roman", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.edgecolor": "#2A2F36",
    "axes.linewidth": 0.6,
    "axes.grid": True,
    "grid.color": "#D9DCE0",
    "grid.linewidth": 0.5,
    "lines.linewidth": 1.4,
    "lines.markersize": 4.5,
    "legend.frameon": False,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})


def _tamano(n: int) -> str:
    return f"{n // 1000}K" if n % 1000 == 0 else str(n)


def _coma(v, _pos=None) -> str:
    return f"{v:g}".replace(".", ",")


def cargar(ruta):
    tipo = ""
    datos = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with open(ruta, newline="") as f:
        for fila in csv.DictReader(f):
            fila["n"] = int(fila["n"])
            fila["recall"] = float(fila["recall"])
            fila["tiempo_ms"] = float(fila["tiempo_ms"])
            fila["valor"] = int(fila["valor"]) if fila["valor"] else None
            datos[fila["metrica"]][fila["n"]][fila["indice"]].append(fila)
            tipo = fila["datos"].split("_")[0]
    for por_n in datos.values():
        for por_indice in por_n.values():
            for filas in por_indice.values():
                filas.sort(key=lambda f: f["valor"] or 0)
    return tipo, datos


def graficar(tipo, metrica, por_n, objetivo, salida):
    # recall contra el valor del parametro, una linea por tamano; los valores son potencias de 2
    # y se ubican equiespaciados
    fig, ejes = plt.subplots(1, 2, figsize=(6.3, 2.5), sharey=True)
    for ax, (nombre, parametro) in zip(ejes, INDICES):
        valores = sorted({f["valor"] for n in por_n for f in por_n[n].get(nombre, [])})
        posicion = {v: i for i, v in enumerate(valores)}
        for n in sorted(por_n):
            filas = por_n[n].get(nombre, [])
            if not filas:
                continue
            color, marcador = TAMANOS.get(n, (GRIS, "o"))
            ax.plot([posicion[f["valor"]] for f in filas], [f["recall"] for f in filas],
                    color=color, marker=marcador, label=_tamano(n))
            elegido = next((f for f in filas if f["recall"] >= objetivo), None)
            if elegido:
                ax.plot([posicion[elegido["valor"]]], [elegido["recall"]], marker="o", markersize=10,
                        markerfacecolor="none", markeredgecolor=color, markeredgewidth=1.2, linestyle="none")
        ax.axhline(objetivo, color=GRIS, linewidth=0.9, linestyle="--")
        ax.set_xticks(range(len(valores)))
        ax.set_xticklabels([str(v) for v in valores])
        ax.set_xlabel(f"${parametro}$")
        ax.set_title(nombre)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(_coma))
    ejes[0].set_ylabel("Recall@10")
    ejes[0].set_ylim(top=1.02)
    asas, etiquetas = ejes[0].get_legend_handles_labels()
    fig.legend(asas, etiquetas, loc="lower center", ncol=len(asas), bbox_to_anchor=(0.5, 1.0),
               title="Tamaño de la colección", title_fontsize=8)
    fig.tight_layout()
    fig.savefig(salida)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entrada", default=ENTRADA)
    ap.add_argument("--salida", default=os.path.join(BENCH, "results"))
    args = ap.parse_args()
    objetivo = yaml.safe_load(open(os.path.join(BENCH, "config.yaml")))["vector"]["recall_objetivo"]
    os.makedirs(args.salida, exist_ok=True)
    nombre = os.path.splitext(os.path.basename(args.entrada))[0]
    tipo, datos = cargar(args.entrada)
    for metrica, por_n in datos.items():
        ruta = os.path.join(args.salida, f"{nombre}_{metrica}.png")
        graficar(tipo, metrica, por_n, objetivo, ruta)
        print(ruta)


if __name__ == "__main__":
    main()
