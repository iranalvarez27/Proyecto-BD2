import argparse
import csv
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl_cache"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

BENCH_DIR = Path(__file__).resolve().parent
DIR_RESULTS = BENCH_DIR / "results"

# colores del informe
AZUL_UTEC = "#1E3A5F"
AZUL_MEDIO = "#3F6C8F"
NARANJA = "#B8742A"
VERDE = "#4A7C6B"
GRIS = "#6C7480"

SERIES = {
    "SPIMI": dict(color=AZUL_UTEC, marker="s", label="SPIMI propio"),
    "GIN": dict(color=NARANJA, marker="o", label="GIN de PostgreSQL"),
    "TF_IDF": dict(color=AZUL_MEDIO, marker="s", label="TF-IDF"),
    "BM25": dict(color=VERDE, marker="^", label="BM25"),
    "EXACTO": dict(color=GRIS, marker="s", label="k-NN exacto"),
    "HNSW": dict(color=AZUL_UTEC, marker="o", label="HNSW"),
    "IVF": dict(color=NARANJA, marker="D", label="IVF"),
}

GRUPOS = [("1_palabra", "1 término"), ("3_palabras", "3 términos"), ("5_mas_palabras", "5 o más términos")]
TIPOS = [("imagen", "Imágenes"), ("audio", "Audio")]
METRICAS = [("euclidean", "euclidiana"), ("cosine", "coseno")]

ESTILO = {
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
}


def coma(v, _pos=None) -> str:
    texto = f"{v:.0f}" if float(v).is_integer() else f"{v:g}"
    return texto.replace(".", ",")


def _leer_csv(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _etiqueta_n(n: int) -> str:
    return f"{n // 1000}K" if n >= 1000 and n % 1000 == 0 else str(n)


def _eje_tamanos(ax, tamanos, rotulo=True):
    # tamanos equiespaciados: 1K, 10K y 100K quedan a la misma distancia sin escala logaritmica
    ax.set_xticks(range(len(tamanos)))
    ax.set_xticklabels([_etiqueta_n(n) for n in tamanos])
    ax.set_xlim(-0.3, len(tamanos) - 0.7)
    ax.yaxis.set_major_formatter(FuncFormatter(coma))
    if rotulo:
        ax.set_xlabel("Tamaño de la colección")


def _linea(ax, tamanos, valores_por_n, clave, **extra):
    xs = [i for i, n in enumerate(tamanos) if n in valores_por_n]
    ys = [valores_por_n[tamanos[i]] for i in xs]
    estilo = {**SERIES[clave], **extra}
    ax.plot(xs, ys, **estilo)


def _leyenda(fig, ax, ncol):
    manejadores, etiquetas = ax.get_legend_handles_labels()
    fig.legend(manejadores, etiquetas, loc="lower center", ncol=ncol, bbox_to_anchor=(0.5, 1.0))


def _guardar(fig, ruta: Path, generados: list):
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)
    generados.append(ruta)


def graficar_texto(dir_results: Path = DIR_RESULTS) -> list[Path]:
    dir_results = Path(dir_results)
    filas_const = _leer_csv(dir_results / "texto_construccion.csv")
    filas_cons = _leer_csv(dir_results / "texto_consultas.csv")
    generados = []

    with plt.rc_context(ESTILO):
        if filas_const:
            tamanos = sorted({int(f["n"]) for f in filas_const})
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.3, 2.4))
            for clave in ("SPIMI", "GIN"):
                sel = [f for f in filas_const if f["motor"].upper().startswith(clave)]
                _linea(ax1, tamanos, {int(f["n"]): float(f["construccion_s"]) for f in sel}, clave)
                _linea(ax2, tamanos, {int(f["n"]): float(f["disco_mb"]) for f in sel}, clave)
            for ax, titulo, ylabel in ((ax1, "Construcción", "Tiempo (s)"), (ax2, "Espacio en disco", "Tamaño (MB)")):
                _eje_tamanos(ax, tamanos)
                ax.set_title(titulo)
                ax.set_ylabel(ylabel)
                ax.set_ylim(bottom=0)
            _leyenda(fig, ax1, 2)
            _guardar(fig, dir_results / "texto_construccion_disco.png", generados)

        if filas_cons:
            tamanos = sorted({int(f["n"]) for f in filas_cons})

            def serie(motor, grupo, campo):
                return {int(f["n"]): float(f[campo]) for f in filas_cons
                        if f["motor"] == motor and f["grupo_longitud"] == grupo}

            fig, ejes = plt.subplots(1, 3, figsize=(6.3, 2.4))
            for ax, (grupo, titulo) in zip(ejes, GRUPOS):
                for motor in ("TF_IDF", "BM25", "GIN"):
                    _linea(ax, tamanos, serie(motor, grupo, "tiempo_p50_ms"), motor)
                _eje_tamanos(ax, tamanos)
                ax.set_title(titulo)
                ax.set_ylim(bottom=0)
            ejes[0].set_ylabel("Mediana por consulta (ms)")
            _leyenda(fig, ejes[0], 3)
            _guardar(fig, dir_results / "texto_latencia_longitud.png", generados)

            fig, ejes = plt.subplots(2, 3, figsize=(6.3, 4.0), sharey=True, sharex=True)
            for fila, (campo, nombre) in enumerate((("precision_at_10", "Precision@10"), ("recall_at_10", "Recall@10"))):
                for col, (grupo, titulo) in enumerate(GRUPOS):
                    ax = ejes[fila][col]
                    for motor in ("TF_IDF", "BM25", "GIN"):
                        _linea(ax, tamanos, serie(motor, grupo, campo), motor)
                    _eje_tamanos(ax, tamanos, rotulo=fila == 1)
                    ax.set_ylim(0, 1)
                    if fila == 0:
                        ax.set_title(titulo)
                    if col == 0:
                        ax.set_ylabel(nombre)
            _leyenda(fig, ejes[0][0], 3)
            _guardar(fig, dir_results / "texto_relevancia_pr10.png", generados)

    for r in generados:
        print(f"[plots] Gráfico de texto guardado en: {r}")
    return generados


def graficar_vector(dir_results: Path = DIR_RESULTS) -> list[Path]:
    dir_results = Path(dir_results)
    filas = _leer_csv(dir_results / "vector_compare.csv")
    if not filas:
        return []

    generados = []
    tipos = [t for t in TIPOS if any(f["tipo"] == t[0] for f in filas)]
    metricas = [m for m in METRICAS if any(f["metrica"] == m[0] for f in filas)]
    tamanos = sorted({int(f["n"]) for f in filas})

    def serie(tipo, metrica, indice, campo):
        return {int(f["n"]): float(f[campo]) for f in filas
                if f["tipo"] == tipo and f["metrica"] == metrica and f["indice"] == indice}

    with plt.rc_context(ESTILO):
        fig, ejes = plt.subplots(len(tipos), len(metricas), figsize=(6.3, 2.2 * len(tipos) + 0.2),
                                 squeeze=False, sharex=True)
        for i, (tipo, nombre_tipo) in enumerate(tipos):
            for j, (metrica, nombre_metrica) in enumerate(metricas):
                ax = ejes[i][j]
                # el k-NN exacto crece hasta dos ordenes de magnitud mas y aplastaria a los otros dos
                for indice in ("HNSW", "IVF"):
                    _linea(ax, tamanos, serie(tipo, metrica, indice, "tiempo_ms"), indice)
                _eje_tamanos(ax, tamanos, rotulo=i == len(tipos) - 1)
                ax.set_ylim(bottom=0)
                ax.set_title(f"{nombre_tipo}, distancia {nombre_metrica}")
                if j == 0:
                    ax.set_ylabel("Mediana por consulta (ms)")
        _leyenda(fig, ejes[0][0], 2)
        _guardar(fig, dir_results / "vector_tiempo_vs_tamano.png", generados)

        fig, ejes = plt.subplots(1, len(tipos), figsize=(6.3, 2.5), squeeze=False)
        for ax, (tipo, nombre_tipo) in zip(ejes[0], tipos):
            for indice in ("HNSW", "IVF"):
                for metrica, nombre_metrica in metricas:
                    extra = {"label": f"{indice}, {nombre_metrica}"}
                    if metrica == "euclidean":
                        extra.update(linestyle="--", markerfacecolor="white")
                    _linea(ax, tamanos, serie(tipo, metrica, indice, "construccion_s"), indice, **extra)
            _eje_tamanos(ax, tamanos)
            ax.set_ylim(bottom=0)
            ax.set_title(nombre_tipo)
        ejes[0][0].set_ylabel("Construcción (s)")
        _leyenda(fig, ejes[0][0], 4)
        _guardar(fig, dir_results / "vector_construccion.png", generados)

        fig, ejes = plt.subplots(len(tipos), len(metricas), figsize=(6.3, 2.2 * len(tipos) + 0.2),
                                 squeeze=False, sharex=True, sharey=True)
        for i, (tipo, nombre_tipo) in enumerate(tipos):
            for j, (metrica, nombre_metrica) in enumerate(metricas):
                ax = ejes[i][j]
                for indice in ("HNSW", "IVF"):
                    _linea(ax, tamanos, serie(tipo, metrica, indice, "recall_at_10"), indice)
                _eje_tamanos(ax, tamanos, rotulo=i == len(tipos) - 1)
                ax.set_ylim(0.5, 1.02)
                ax.set_title(f"{nombre_tipo}, distancia {nombre_metrica}")
                if j == 0:
                    ax.set_ylabel("Recall@10")
        _leyenda(fig, ejes[0][0], 2)
        _guardar(fig, dir_results / "vector_recall_comparativa.png", generados)

    for r in generados:
        print(f"[plots] Gráfico vectorial guardado en: {r}")
    return generados


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parte",
        default="todo",
        choices=("texto", "vector", "todo"),
        help="Qué conjunto de gráficos generar (por defecto: todo)",
    )
    parser.add_argument("--results-dir", default=str(DIR_RESULTS))
    args = parser.parse_args(argv)

    dir_res = Path(args.results_dir)
    if args.parte in ("texto", "todo"):
        graficar_texto(dir_res)
    if args.parte in ("vector", "todo"):
        graficar_vector(dir_res)


if __name__ == "__main__":
    main()
