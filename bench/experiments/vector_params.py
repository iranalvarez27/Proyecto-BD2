"""Barrido de efSearch (HNSW) y nprobe (IVF): Recall@10 y tiempo por valor."""
import argparse
import csv
import os
import sys
import time

# un hilo: con los de FAISS y BLAS compitiendo la latencia por consulta variaba hasta 2x entre corridas
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np
import yaml

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(BENCH))

from bench.experiments.evaluacion import medir_tiempo, recall_vs_exacto
from index.vector.exacto import knn_exacto_lote
from index.vector.hnsw import HNSW
from index.vector.ivf import IVF

CONFIG = os.path.join(BENCH, "config.yaml")
SALIDA = os.path.join(BENCH, "results", "vector_params.csv")
METRICAS = ("euclidean", "cosine")
CAMPOS = ["datos", "n", "dim", "metrica", "indice", "parametro", "valor",
          "recall", "tiempo_ms", "construccion_s", "nlist"]


def sinteticos(rng, n, dim, grupos, separacion):
    # separacion = escala de los centros respecto del ruido de cada grupo (desvio 1)
    centros = rng.normal(size=(grupos, dim)) * separacion
    return (centros[rng.integers(0, grupos, n)] + rng.normal(size=(n, dim))).astype(np.float32)


def cargar_datos(args, cfg, rng):
    """Devuelve (base, consultas, nombre); las consultas no estan en la base."""
    nq = cfg["vector"]["consultas"]
    if args.vectores:
        todo = np.load(args.vectores).astype(np.float32)
        todo = todo[rng.permutation(len(todo))]
        return todo[nq:], todo[:nq], os.path.basename(args.vectores)
    todo = sinteticos(rng, max(args.tamanos) + nq, args.dim, args.grupos, args.separacion)
    return todo[nq:], todo[:nq], f"sintetico_{args.grupos}g_sep{args.separacion}"


def medir(fn, q, args):
    """Cada consulta se corre `repeticiones` veces; tiempo = mediana de todas las corridas."""
    res, t = medir_tiempo(fn, np.tile(q, (args.repeticiones, 1)), args.calentamiento)
    return res[:len(q)], float(np.median(t))


def barrer(indice, nombre, parametro, valores, q, exactos, k, args):
    filas = []
    for v in valores:
        res, t = medir(lambda c: indice.search_lote(c, k, **{parametro: v})[0][0], q, args)
        filas.append({"indice": nombre, "parametro": parametro, "valor": v,
                      "recall": recall_vs_exacto(res, exactos), "tiempo_ms": t})
    return filas


def primero_que_llega(filas, objetivo):
    for f in filas:
        if f["recall"] >= objetivo:
            return f
    return None


def main():
    cfg = yaml.safe_load(open(CONFIG))
    vcfg = cfg["vector"]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vectores", help=".npy N x d con vectores reales; sin esto usa sinteticos agrupados")
    ap.add_argument("--tamanos", type=int, nargs="+", default=cfg["tamanos"])
    ap.add_argument("--metricas", nargs="+", default=list(METRICAS))
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--grupos", type=int, default=100)
    ap.add_argument("--separacion", type=float, default=0.5)
    ap.add_argument("--calentamiento", type=int, default=50)
    ap.add_argument("--repeticiones", type=int, default=5)
    ap.add_argument("--salida", default=SALIDA)
    args = ap.parse_args()

    k, objetivo = cfg["k"], vcfg["recall_objetivo"]
    rng = np.random.default_rng(cfg["semilla"])
    base, q, datos = cargar_datos(args, cfg, rng)
    tamanos = [n for n in args.tamanos if n <= len(base)]
    if len(tamanos) < len(args.tamanos):
        print(f"se saltan los tamanos mayores a {len(base)}: {[n for n in args.tamanos if n > len(base)]}")
    nlist_cfg = vcfg["ivf"]["nlist"]
    print(f"datos {datos}: {len(base)} vectores de dim {base.shape[1]}, {len(q)} consultas, k {k}")

    filas, optimos = [], {}
    for n in tamanos:
        x = base[:n]
        for m in args.metricas:
            comunes = {"datos": datos, "n": n, "dim": x.shape[1], "metrica": m}
            exactos, t_exacto = medir(lambda c: knn_exacto_lote(c, x, k, m)[0][0], q, args)
            filas.append({**comunes, "indice": "exacto", "recall": 1.0, "tiempo_ms": t_exacto})

            hnsw = HNSW(m, M=vcfg["hnsw"]["M"], efConstruction=vcfg["hnsw"]["efConstruction"])
            ivf = IVF(m, nlist=None if nlist_cfg == "sqrt" else int(nlist_cfg), semilla=cfg["semilla"])
            for indice, nombre, parametro, valores in (
                    (hnsw, "HNSW", "efSearch", vcfg["barrido"]["efSearch"]),
                    (ivf, "IVF", "nprobe", vcfg["barrido"]["nprobe"])):
                t0 = time.perf_counter()
                indice.build(x)
                construccion = time.perf_counter() - t0
                nlist = ivf.nlist if indice is ivf else ""
                if indice is ivf:
                    valores = [v for v in valores if v <= ivf.nlist]
                barrido = barrer(indice, nombre, parametro, valores, q, exactos, k, args)
                for f in barrido:
                    filas.append({**comunes, **f, "construccion_s": round(construccion, 4), "nlist": nlist})
                optimos[(m, nombre, n)] = (primero_que_llega(barrido, objetivo), max(f["recall"] for f in barrido))
                primero, ultimo = barrido[0], barrido[-1]
                print(f"  n {n:>7} {m:<10} {nombre:<5} build {construccion:6.2f}s  "
                      f"recall {primero['recall']:.3f}..{ultimo['recall']:.3f}  "
                      f"tiempo {primero['tiempo_ms']:.3f}..{ultimo['tiempo_ms']:.3f} ms  "
                      f"(exacto {t_exacto:.3f} ms)")

    os.makedirs(os.path.dirname(args.salida), exist_ok=True)
    with open(args.salida, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, restval="")
        w.writeheader()
        w.writerows(filas)
    print(f"\n{len(filas)} filas en {args.salida}")

    print(f"\nprimer valor con Recall@{k} >= {objetivo} (para vector.busqueda en config.yaml):")
    print("busqueda:")
    for m in args.metricas:
        print(f"  {m}:")
        for nombre, parametro in (("HNSW", "efSearch"), ("IVF", "nprobe")):
            valores = []
            for n in tamanos:
                f, maximo = optimos[(m, nombre, n)]
                valores.append(f"{n}: {f['valor'] if f else 'null'}")
                if f is None:
                    print(f"    # {nombre} n {n}: no llega, maximo {maximo:.3f}")
            print(f"    {parametro}: {{{', '.join(valores)}}}")


if __name__ == "__main__":
    main()
