"""Graficos generados desde los CSV de results/ para las Partes 3 (Texto) y 4 (Vector/Multimedia)."""
import argparse
import csv
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl_cache"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BENCH_DIR = Path(__file__).resolve().parent
DIR_RESULTS = BENCH_DIR / "results"

COLORES_TEXTO = {
    "TF_IDF": "#2563eb",
    "BM25": "#16a34a",
    "GIN": "#ea580c",
}

COLORES_VECTOR = {
    "EXACTO": "#475569",
    "HNSW": "#2563eb",
    "IVF": "#d97706",
}

ETIQUETAS_LONGITUD = {
    "1_palabra": "1 palabra",
    "3_palabras": "3 palabras",
    "5_mas_palabras": "5+ palabras",
}


def _leer_csv(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _etiqueta_n(n: int) -> str:
    return f"{n // 1000}k" if n >= 1000 and n % 1000 == 0 else str(n)


def graficar_texto(dir_results: Path = DIR_RESULTS) -> list[Path]:
    """Genera las 3 figuras de la Parte 3 comparando todos los tamaños N (1k, 10k, 100k)."""
    dir_results = Path(dir_results)
    filas_const = _leer_csv(dir_results / "texto_construccion.csv")
    filas_cons = _leer_csv(dir_results / "texto_consultas.csv")
    generados = []

    if filas_const:
        tamanos = sorted({int(f["n"]) for f in filas_const})
        motores = ["TF_IDF", "BM25", "GIN"]
        x = np.arange(len(tamanos))
        ancho = 0.25

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), dpi=150)
        fig.suptitle(
            "Parte 3 (Full-Text Search): Construcción del Índice y Espacio en Disco (1k, 10k, 100k)",
            fontsize=13,
            fontweight="bold",
        )

        for idx, m in enumerate(motores):
            tiempos = []
            discos = []
            for n in tamanos:
                match = next((f for f in filas_const if int(f["n"]) == n and f["motor"] == m), None)
                tiempos.append(float(match["construccion_s"]) if match else 0.0)
                discos.append(float(match["disco_mb"]) if match else 0.0)

            despl = (idx - 1) * ancho
            b1 = ax1.bar(x + despl, tiempos, width=ancho, label=m, color=COLORES_TEXTO.get(m, "#333"))
            b2 = ax2.bar(x + despl, discos, width=ancho, label=m, color=COLORES_TEXTO.get(m, "#333"))
            ax1.bar_label(b1, fmt="%.2fs", padding=2, fontsize=8)
            ax2.bar_label(b2, fmt="%.2f", padding=2, fontsize=8)

        for ax, titulo, ylabel in (
            (ax1, "Tiempo de Construcción por Tamaño (N)", "Tiempo (segundos)"),
            (ax2, "Uso de Espacio en Disco por Tamaño (N)", "Espacio en Disco (MB)"),
        ):
            ax.set_title(titulo, fontsize=11, fontweight="bold")
            ax.set_xticks(x)
            ax.set_xticklabels([_etiqueta_n(n) for n in tamanos])
            ax.set_xlabel("Tamaño de colección (documentos)")
            ax.set_ylabel(ylabel)
            ax.grid(axis="y", linestyle="--", alpha=0.4)
            ax.legend()

        plt.tight_layout()
        ruta1 = dir_results / "texto_construccion_disco.png"
        fig.savefig(ruta1, bbox_inches="tight")
        plt.close(fig)
        generados.append(ruta1)

    if filas_cons:
        tamanos = sorted({int(f["n"]) for f in filas_cons})
        grupos = ["1_palabra", "3_palabras", "5_mas_palabras"]
        motores = ["TF_IDF", "BM25", "GIN"]

        # Figura 2: Latencia por longitud de consulta en cada tamaño N (1k, 10k, 100k)
        fig, axes = plt.subplots(1, len(tamanos), figsize=(5.2 * max(1, len(tamanos)), 4.8), dpi=150, sharey=False)
        if len(tamanos) == 1:
            axes = [axes]
        fig.suptitle(
            "Parte 3: Latencia de Consulta (ms) por Longitud de Consulta y Tamaño (1k, 10k, 100k)",
            fontsize=13,
            fontweight="bold",
        )

        x = np.arange(len(grupos))
        ancho = 0.25
        for ax, n in zip(axes, tamanos):
            for idx, m in enumerate(motores):
                vals = []
                for g in grupos:
                    match = next(
                        (f for f in filas_cons if int(f["n"]) == n and f["motor"] == m and f["grupo_longitud"] == g),
                        None,
                    )
                    vals.append(float(match["tiempo_medio_ms"]) if match else 0.0)
                barras = ax.bar(
                    x + (idx - 1) * ancho,
                    vals,
                    width=ancho,
                    label=m,
                    color=COLORES_TEXTO.get(m, "#333"),
                )
                ax.bar_label(barras, fmt="%.2f", padding=2, fontsize=7.5)

            ax.set_title(f"Colección N = {n:,} ({_etiqueta_n(n)})", fontsize=11, fontweight="bold")
            ax.set_xticks(x)
            ax.set_xticklabels([ETIQUETAS_LONGITUD[g] for g in grupos])
            ax.set_ylabel("Tiempo medio por consulta (ms)")
            ax.grid(axis="y", linestyle="--", alpha=0.4)
            ax.legend()

        plt.tight_layout()
        ruta2 = dir_results / "texto_latencia_longitud.png"
        fig.savefig(ruta2, bbox_inches="tight")
        plt.close(fig)
        generados.append(ruta2)

        # Figura 3: Relevancia Precision@10 y Recall@10 para TODOS los tamaños (2 filas x len(tamanos) columnas)
        fig, axes = plt.subplots(
            2,
            len(tamanos),
            figsize=(5.2 * max(1, len(tamanos)), 8.2),
            dpi=150,
            squeeze=False,
        )
        fig.suptitle(
            "Parte 3: Calidad de Recuperación (Precision@10 y Recall@10) por Tamaño y Longitud de Consulta",
            fontsize=13,
            fontweight="bold",
        )

        for col_idx, n in enumerate(tamanos):
            ax_p = axes[0, col_idx]
            ax_r = axes[1, col_idx]
            for idx, m in enumerate(motores):
                p_vals, r_vals = [], []
                for g in grupos:
                    match = next(
                        (f for f in filas_cons if int(f["n"]) == n and f["motor"] == m and f["grupo_longitud"] == g),
                        None,
                    )
                    p_vals.append(float(match["precision_at_10"]) if match else 0.0)
                    r_vals.append(float(match["recall_at_10"]) if match else 0.0)

                b_p = ax_p.bar(x + (idx - 1) * ancho, p_vals, width=ancho, label=m, color=COLORES_TEXTO.get(m, "#333"))
                b_r = ax_r.bar(x + (idx - 1) * ancho, r_vals, width=ancho, label=m, color=COLORES_TEXTO.get(m, "#333"))
                ax_p.bar_label(b_p, fmt="%.2f", padding=2, fontsize=7.5)
                ax_r.bar_label(b_r, fmt="%.2f", padding=2, fontsize=7.5)

            ax_p.set_title(f"Precision@10 — N = {n:,} ({_etiqueta_n(n)})", fontsize=10.5, fontweight="bold")
            ax_p.set_xticks(x)
            ax_p.set_xticklabels([ETIQUETAS_LONGITUD[g] for g in grupos])
            ax_p.set_ylabel("Precision@10")
            ax_p.set_ylim(0, 1.12)
            ax_p.grid(axis="y", linestyle="--", alpha=0.4)
            ax_p.legend(fontsize=8)

            ax_r.set_title(f"Recall@10 — N = {n:,} ({_etiqueta_n(n)})", fontsize=10.5, fontweight="bold")
            ax_r.set_xticks(x)
            ax_r.set_xticklabels([ETIQUETAS_LONGITUD[g] for g in grupos])
            ax_r.set_ylabel("Recall@10")
            ax_r.set_ylim(0, 1.12)
            ax_r.grid(axis="y", linestyle="--", alpha=0.4)
            ax_r.legend(fontsize=8)

        plt.tight_layout()
        ruta3 = dir_results / "texto_relevancia_pr10.png"
        fig.savefig(ruta3, bbox_inches="tight")
        plt.close(fig)
        generados.append(ruta3)

    for r in generados:
        print(f"[plots] Gráfico de texto guardado en: {r}")
    return generados


def graficar_vector(dir_results: Path = DIR_RESULTS) -> list[Path]:
    """Genera las 3 figuras de la Parte 4 comparando todos los tamaños N (1k, 10k, 100k)."""
    dir_results = Path(dir_results)
    filas = _leer_csv(dir_results / "vector_compare.csv")
    if not filas:
        return []

    generados = []
    tipos = [t for t in ("imagen", "audio") if any(f["tipo"] == t for f in filas)]
    metricas = [m for m in ("euclidean", "cosine") if any(f["metrica"] == m for f in filas)]
    indices = ["EXACTO", "HNSW", "IVF"]

    # Figura 1: Tiempo de consulta vs tamaño N por (tipo, metrica)
    fig, axes = plt.subplots(
        len(tipos),
        len(metricas),
        figsize=(6.4 * len(metricas), 4.6 * len(tipos)),
        dpi=150,
        squeeze=False,
    )
    fig.suptitle(
        "Parte 4 (Multimedia): Tiempo de Consulta por Vector (ms) según Tamaño (1k, 10k, 100k)",
        fontsize=13,
        fontweight="bold",
    )

    for i_t, tipo in enumerate(tipos):
        for i_m, metrica in enumerate(metricas):
            ax = axes[i_t, i_m]
            sub = [f for f in filas if f["tipo"] == tipo and f["metrica"] == metrica]
            tamanos = sorted({int(f["n"]) for f in sub})
            x = np.arange(len(tamanos))
            ancho = 0.25

            for idx, ind in enumerate(indices):
                tiempos = []
                for n in tamanos:
                    match = next((f for f in sub if int(f["n"]) == n and f["indice"] == ind), None)
                    tiempos.append(float(match["tiempo_ms"]) if match else 0.0)
                barras = ax.bar(
                    x + (idx - 1) * ancho,
                    tiempos,
                    width=ancho,
                    label=ind,
                    color=COLORES_VECTOR.get(ind, "#333"),
                )
                ax.bar_label(barras, fmt="%.3f", padding=2, fontsize=7.5)

            ax.set_title(f"Dominio: {tipo.upper()} — Métrica: {metrica}", fontsize=10.5, fontweight="bold")
            ax.set_xticks(x)
            ax.set_xticklabels([_etiqueta_n(n) for n in tamanos])
            ax.set_xlabel("Tamaño de colección (N)")
            ax.set_ylabel("Latencia por consulta (ms)")
            ax.grid(axis="y", linestyle="--", alpha=0.4)
            ax.legend()

    plt.tight_layout()
    ruta1 = dir_results / "vector_tiempo_vs_tamano.png"
    fig.savefig(ruta1, bbox_inches="tight")
    plt.close(fig)
    generados.append(ruta1)

    # Figura 2: Tiempo de construcción y Uso de Memoria en función de N (1k, 10k, 100k) para cada dominio
    fig, axes = plt.subplots(
        len(tipos),
        2,
        figsize=(13.5, 4.6 * len(tipos)),
        dpi=150,
        squeeze=False,
    )
    fig.suptitle(
        "Parte 4: Tiempo de Construcción (s) y Uso de Memoria (MB) por Tamaño (1k, 10k, 100k)",
        fontsize=13,
        fontweight="bold",
    )

    for i_t, tipo in enumerate(tipos):
        ax_b = axes[i_t, 0]
        ax_m = axes[i_t, 1]
        sub_tipo = [f for f in filas if f["tipo"] == tipo]
        tamanos = sorted({int(f["n"]) for f in sub_tipo})
        x = np.arange(len(tamanos))
        ancho = 0.25

        for idx, ind in enumerate(indices):
            builds, mems = [], []
            for n in tamanos:
                # Promedio entre metricas (el uso de memoria es identico y el tiempo de build es muy similar)
                matches = [f for f in sub_tipo if int(f["n"]) == n and f["indice"] == ind]
                builds.append(float(np.mean([float(m["construccion_s"]) for m in matches])) if matches else 0.0)
                mems.append(float(np.mean([float(m["memoria_mb"]) for m in matches])) if matches else 0.0)

            b1 = ax_b.bar(x + (idx - 1) * ancho, builds, width=ancho, label=ind, color=COLORES_VECTOR.get(ind, "#333"))
            b2 = ax_m.bar(x + (idx - 1) * ancho, mems, width=ancho, label=ind, color=COLORES_VECTOR.get(ind, "#333"))
            ax_b.bar_label(b1, fmt="%.3fs", padding=2, fontsize=7.5)
            ax_m.bar_label(b2, fmt="%.2f", padding=2, fontsize=7.5)

        ax_b.set_title(f"{tipo.upper()} — Tiempo de Construcción vs Tamaño (N)", fontsize=11, fontweight="bold")
        ax_b.set_xticks(x)
        ax_b.set_xticklabels([_etiqueta_n(n) for n in tamanos])
        ax_b.set_xlabel("Tamaño de colección (N)")
        ax_b.set_ylabel("Segundos")
        ax_b.grid(axis="y", linestyle="--", alpha=0.4)
        ax_b.legend()

        ax_m.set_title(f"{tipo.upper()} — Memoria / Espacio Serializado (MB) vs Tamaño (N)", fontsize=11, fontweight="bold")
        ax_m.set_xticks(x)
        ax_m.set_xticklabels([_etiqueta_n(n) for n in tamanos])
        ax_m.set_xlabel("Tamaño de colección (N)")
        ax_m.set_ylabel("Megabytes (MB)")
        ax_m.grid(axis="y", linestyle="--", alpha=0.4)
        ax_m.legend()

    plt.tight_layout()
    ruta2 = dir_results / "vector_construccion_memoria.png"
    fig.savefig(ruta2, bbox_inches="tight")
    plt.close(fig)
    generados.append(ruta2)

    # Figura 3: Recall@10 y Speedup vs Exacto para TODOS los tamaños N (1k, 10k, 100k)
    fig, axes = plt.subplots(
        len(tipos),
        len(metricas),
        figsize=(6.4 * len(metricas), 4.6 * len(tipos)),
        dpi=150,
        squeeze=False,
    )
    fig.suptitle(
        "Parte 4: Recall@10 (HNSW vs IVF) por Tamaño de Colección (1k, 10k, 100k)",
        fontsize=13,
        fontweight="bold",
    )

    for i_t, tipo in enumerate(tipos):
        for i_m, metrica in enumerate(metricas):
            ax = axes[i_t, i_m]
            sub = [f for f in filas if f["tipo"] == tipo and f["metrica"] == metrica]
            tamanos = sorted({int(f["n"]) for f in sub})
            x = np.arange(len(tamanos))
            ancho = 0.30

            for idx, ind in enumerate(("HNSW", "IVF")):
                recalls = []
                for n in tamanos:
                    match = next((f for f in sub if int(f["n"]) == n and f["indice"] == ind), None)
                    recalls.append(float(match["recall_at_10"]) if match else 0.0)
                despl = (idx - 0.5) * ancho
                br = ax.bar(x + despl, recalls, width=ancho, label=ind, color=COLORES_VECTOR.get(ind, "#333"))
                ax.bar_label(br, fmt="%.3f", padding=2, fontsize=8)

            ax.axhline(1.0, color="#475569", linestyle=":", linewidth=1.2, label="EXACTO (1.000)")
            ax.set_title(f"Dominio: {tipo.upper()} — Métrica: {metrica}", fontsize=10.5, fontweight="bold")
            ax.set_xticks(x)
            ax.set_xticklabels([_etiqueta_n(n) for n in tamanos])
            ax.set_xlabel("Tamaño de colección (N)")
            ax.set_ylabel("Recall@10")
            ax.set_ylim(0, 1.12)
            ax.grid(axis="y", linestyle="--", alpha=0.4)
            ax.legend(loc="lower right", fontsize=8.5)

    plt.tight_layout()
    ruta3 = dir_results / "vector_recall_comparativa.png"
    fig.savefig(ruta3, bbox_inches="tight")
    plt.close(fig)
    generados.append(ruta3)

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
