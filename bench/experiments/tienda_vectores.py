"""Exacto vs HNSW vs IVF sobre los embeddings ResNet-50 de la tienda.

El recomendador pide los 100 vecinos visuales de un producto del catalogo, asi que se mide
Recall@100 contra el k-NN exacto (coseno) y el tiempo por consulta, barriendo efSearch y
nprobe. Con --guardar escribe en recomendacion/parametros.yaml el menor valor de cada
indice que alcanza el recall objetivo; la tienda construye sus indices con esos valores.
"""
import argparse
import csv
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl_cache"))
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from index.vector.exacto import knn_exacto, knn_exacto_lote
from index.vector.hnsw import HNSW
from index.vector.ivf import IVF

DIR_RESULTS = BENCH_DIR / "results"
CSV_RESULTADOS = DIR_RESULTS / "tienda_vectores.csv"
PNG_RESULTADOS = DIR_RESULTS / "tienda_vectores.png"
PARAMETROS = PROJECT_ROOT / "recomendacion" / "parametros.yaml"
CACHE = PROJECT_ROOT / "data" / "ecommerce_vectores_cnn.npz"
K = 100
EF_SEARCH = (100, 128, 160, 200, 256, 320, 400, 512)
NPROBE = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64)


def recall(pos, exactos) -> float:
    return float(np.mean([len(set(p) & set(e)) / len(e) for p, e in zip(pos, exactos)]))


def ms_por_consulta(buscar, consultas) -> float:
    inicio = time.perf_counter()
    for q in consultas:
        buscar(q)
    return (time.perf_counter() - inicio) / len(consultas) * 1000


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consultas", type=int, default=500)
    parser.add_argument("--objetivo", type=float, default=0.95, help="Recall@100 minimo")
    parser.add_argument("--guardar", action="store_true", help="escribe recomendacion/parametros.yaml")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args(argv)

    with np.load(CACHE) as f:
        vectores = f["vectores"].astype(np.float32)
    n = len(vectores)
    rng = np.random.default_rng(42)
    consultas = vectores[rng.choice(n, size=min(args.consultas, n), replace=False)]
    exactos, _ = knn_exacto_lote(consultas, vectores, K, "cosine")
    filas = [["exacto", "", "", n, K, 1.0, ms_por_consulta(lambda q: knn_exacto(q, vectores, K, "cosine"), consultas), ""]]
    print(f"[tienda_vectores] n={n:,} dim={vectores.shape[1]} exacto {filas[0][6]:.3f} ms")

    for nombre, clase, parametro, valores in (("HNSW", HNSW, "efSearch", EF_SEARCH), ("IVF", IVF, "nprobe", NPROBE)):
        indice = clase("cosine")
        inicio = time.perf_counter()
        indice.build(vectores)
        construccion = time.perf_counter() - inicio
        for valor in valores:
            pos, _ = indice.search_lote(consultas, K, **{parametro: valor})
            ms = ms_por_consulta(lambda q: indice.search_lote(q[None, :], K, **{parametro: valor}), consultas)
            filas.append([nombre, parametro, valor, n, K, round(recall(pos, exactos), 4), ms, round(construccion, 2)])
            print(f"[tienda_vectores] {nombre} {parametro}={valor:<4} recall@{K} {filas[-1][5]:.3f}  {ms:.3f} ms")

    DIR_RESULTS.mkdir(parents=True, exist_ok=True)
    with open(CSV_RESULTADOS, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["indice", "parametro", "valor", "n", "k", "recall", "tiempo_ms", "construccion_s"])
        escritor.writerows(filas)

    elegidos = {}
    for nombre in ("HNSW", "IVF"):
        candidatos = [f for f in filas if f[0] == nombre and f[5] >= args.objetivo]
        if candidatos:
            f = min(candidatos, key=lambda f: f[2])
            elegidos[nombre] = {f[1]: f[2], "recall": f[5], "tiempo_ms": round(f[6], 3)}
        else:
            print(f"[tienda_vectores] {nombre} no alcanza recall {args.objetivo}")
    print(f"[tienda_vectores] elegidos: {elegidos}")
    if args.guardar:
        import yaml
        datos = {"n": n, "k": K, "objetivo_recall": args.objetivo, "exacto_ms": round(filas[0][6], 3), **elegidos}
        PARAMETROS.write_text("# lo escribe bench/experiments/tienda_vectores.py --guardar\n"
                              + yaml.safe_dump(datos, sort_keys=False))
        print(f"[tienda_vectores] parametros en {PARAMETROS}")
    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, eje = plt.subplots(figsize=(6, 4))
        for nombre in ("HNSW", "IVF"):
            puntos = [f for f in filas if f[0] == nombre]
            eje.plot([f[6] for f in puntos], [f[5] for f in puntos], marker="o", label=nombre)
        eje.axvline(filas[0][6], color="gray", linestyle="--", label="exacto")
        eje.axhline(args.objetivo, color="gray", linestyle=":")
        eje.set_xlabel("ms por consulta")
        eje.set_ylabel(f"Recall@{K}")
        eje.legend()
        fig.tight_layout()
        fig.savefig(PNG_RESULTADOS, dpi=120)
        print(f"[tienda_vectores] grafico en {PNG_RESULTADOS}")


if __name__ == "__main__":
    main()
