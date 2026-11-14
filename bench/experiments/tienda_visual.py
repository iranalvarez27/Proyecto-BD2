"""Descriptor visual de la tienda: SIFT-BoVW vs ResNet-50 con cuatro preprocesamientos.

Mide, sobre el catalogo curado, que fraccion de los 10 vecinos exactos (coseno) de cada
producto comparte su subcategoria y su categoria. Con --plot arma la galeria de vecinos
de un producto tipico (el mas resenado) de varias categorias, SIFT contra la CNN.
"""
import argparse
import csv
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl_cache"))

import numpy as np

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from index.vector.exacto import knn_exacto_lote
from recomendacion.catalogo import DIR_IMAGENES, DIR_TIENDA
from recomendacion.visual import MODOS, ExtractorCNN

DIR_RESULTS = BENCH_DIR / "results"
CSV_RESULTADOS = DIR_RESULTS / "tienda_visual.csv"
PNG_GALERIA = DIR_RESULTS / "tienda_visual_galeria.png"
GALERIA_CATEGORIAS = ("Audio", "Cameras", "Laptops & Computers", "Monitors", "Peripherals", "Smartwatches")
GALERIA_DESCRIPTORES = {"sift": "SIFT-BoVW", "cnn_estirar": "ResNet-50"}
DESCRIPTORES = ("sift",) + tuple(f"cnn_{m}" for m in MODOS)
K = 10


def productos():
    with open(DIR_TIENDA / "productos.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def vectores(descriptor: str, rutas: list) -> np.ndarray:
    """Calcula o reutiliza los vectores del catalogo (cache en data/tienda)."""
    cache = DIR_TIENDA / f"vectores_{descriptor}.npy"
    if cache.exists():
        guardados = np.load(cache)
        if len(guardados) == len(rutas):
            return guardados
    inicio = time.perf_counter()
    if descriptor == "sift":
        from multimedia.bovw import Extractor
        extractor = Extractor("imagen", n_coleccion=100000)
        v = np.stack([extractor(r) for r in rutas]).astype(np.float32)
    else:
        v = ExtractorCNN(descriptor.removeprefix("cnn_")).lote(rutas)
    print(f"[tienda_visual] {descriptor}: {len(rutas):,} imagenes en {time.perf_counter() - inicio:.0f}s", flush=True)
    np.save(cache, v)
    return v


def vecinos(v: np.ndarray, k: int = K, bloque: int = 1000) -> np.ndarray:
    filas = []
    for i in range(0, len(v), bloque):
        pos, _ = knn_exacto_lote(v[i:i + bloque], v, k + 1, "cosine")
        # se descarta el propio producto
        filas.append(np.array([[j for j in fila if j != i + n][:k] for n, fila in enumerate(pos)]))
    return np.concatenate(filas)


def coincidencia(vec: np.ndarray, etiquetas: np.ndarray) -> float:
    return float((etiquetas[vec] == etiquetas[:, None]).mean())


def galeria(prods, resultados, mostrar: int = 5):
    import cv2
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    descriptores = [d for d in GALERIA_DESCRIPTORES if d in resultados]
    consultas = [max((i for i, p in enumerate(prods) if p["categoria"] == c), key=lambda i: int(prods[i]["num_resenas"]))
                 for c in GALERIA_CATEGORIAS]
    filas = len(consultas) * len(descriptores)
    fig, ejes = plt.subplots(filas, mostrar + 1, figsize=(1.5 * (mostrar + 1), 1.5 * filas))
    for c, q in enumerate(consultas):
        for d, descriptor in enumerate(descriptores):
            fila = c * len(descriptores) + d
            for col, j in enumerate([q] + list(resultados[descriptor][q][:mostrar])):
                eje = ejes[fila, col]
                imagen = cv2.cvtColor(cv2.imread(str(DIR_IMAGENES / f"{prods[j]['asin']}.jpg")), cv2.COLOR_BGR2RGB)
                eje.imshow(imagen)
                eje.set_xticks([])
                eje.set_yticks([])
                if col and prods[j]["subcategoria"] != prods[q]["subcategoria"]:
                    for borde in eje.spines.values():
                        borde.set_edgecolor("red")
                        borde.set_linewidth(2.5)
            ejes[fila, 0].set_ylabel(GALERIA_DESCRIPTORES[descriptor], fontsize=8)
        ejes[c * len(descriptores), 0].set_title(prods[q]["subcategoria"], fontsize=8)
    fig.tight_layout()
    fig.savefig(PNG_GALERIA, dpi=120)
    print(f"[tienda_visual] galeria en {PNG_GALERIA}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptores", nargs="+", default=list(DESCRIPTORES), choices=DESCRIPTORES)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args(argv)

    prods = productos()
    rutas = [DIR_IMAGENES / f"{p['asin']}.jpg" for p in prods]
    subcat = np.array([p["subcategoria"] for p in prods])
    cat = np.array([p["categoria"] for p in prods])
    resultados, filas = {}, []
    for descriptor in args.descriptores:
        vec = vecinos(vectores(descriptor, rutas))
        resultados[descriptor] = vec
        filas.append([descriptor, len(prods), K, round(coincidencia(vec, subcat), 4), round(coincidencia(vec, cat), 4)])
        print(f"[tienda_visual] {descriptor:13} subcategoria@{K} {filas[-1][3]:.3f}  categoria@{K} {filas[-1][4]:.3f}")
    DIR_RESULTS.mkdir(parents=True, exist_ok=True)
    with open(CSV_RESULTADOS, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["descriptor", "n", "k", "misma_subcategoria", "misma_categoria"])
        escritor.writerows(filas)
    if args.plot:
        galeria(prods, resultados)


if __name__ == "__main__":
    main()
