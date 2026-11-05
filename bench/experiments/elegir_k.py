"""Provisional: K del codebook por tipo, con multimedia.barrido_k y las etiquetas de bench/data.

Calidad de cada K = Precision@10 por categoria (imagen) o genero (audio) de los vecinos exactos.
Se elige el menor K que logra al menos (1 - tolerancia) de la mejor ganancia sobre el azar.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter

BENCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(BENCH))

from multimedia import barrido_k, cache, codebook, config as mcfg

DATASET = {"imagen": "amazon_img", "audio": "fma"}
VALORES_K = {"imagen": (128, 256, 512, 1024), "audio": (64, 128, 256, 512, 1024)}
SALIDA = os.path.join(BENCH, "results", "elegir_k.csv")
CAMPOS = ["tipo", "N", "K", "precision@10", "azar", "ganancia", "segundos_offline",
          "ms_transformacion", "elegido"]


def precision_azar(ids, etiquetas):
    """Precision@10 esperada con vecinos al azar: suma de p^2 por etiqueta."""
    conteo = Counter(barrido_k._etiqueta(i, etiquetas) for i in ids)
    conteo.pop(None, None)
    total = sum(conteo.values())
    return sum((v / total) ** 2 for v in conteo.values())


def elegir(filas, azar, tolerancia):
    validas = [f for f in filas if f.get("precision@10") is not None]
    mejor = max(f["precision@10"] for f in validas) - azar
    return min((f for f in validas if f["precision@10"] - azar >= (1 - tolerancia) * mejor),
               key=lambda f: f["K"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tipos", nargs="+", choices=tuple(DATASET), default=list(DATASET))
    ap.add_argument("--n", type=int, default=10_000, help="objetos de la cache usados en el barrido")
    ap.add_argument("--tolerancia", type=float, default=0.05)
    ap.add_argument("--salida", default=SALIDA)
    args = ap.parse_args()

    ruta_k = mcfg.BASE / "barrido_k" / "k_elegido.json"
    elegidos = json.loads(ruta_k.read_text()) if ruta_k.exists() else {}
    filas_csv = []
    for tipo in args.tipos:
        with open(os.path.join(BENCH, "data", DATASET[tipo], "etiquetas.json"), encoding="utf-8") as f:
            etiquetas = json.load(f)
        filas = barrido_k.barrido_k(tipo, args.n, VALORES_K[tipo], etiquetas=etiquetas)
        azar = precision_azar(cache.ids_objetos(tipo)[:args.n], etiquetas)
        elegido = elegir(filas, azar, args.tolerancia)
        elegidos[tipo] = elegido
        for f in filas:
            if f.get("precision@10") is None:
                continue
            filas_csv.append({**{c: f.get(c) for c in CAMPOS}, "precision@10": round(f["precision@10"], 5),
                              "azar": round(azar, 5),
                              "ganancia": round(f["precision@10"] - azar, 5),
                              "elegido": f["K"] == elegido["K"]})
        actual = int(codebook.cargar_meta(tipo)["k"])
        print(f"[{tipo}] azar {azar:.3f}; K elegido {elegido['K']} "
              f"(precision@10 {elegido['precision@10']:.3f}); colecciones actuales con K {actual}")
        if elegido["K"] != actual:
            print(f"  reconstruir colecciones y tablas: python bench/datasets/{DATASET[tipo]}.py --ingestar")

    os.makedirs(os.path.dirname(args.salida), exist_ok=True)
    with open(args.salida, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas_csv)
    ruta_k.parent.mkdir(parents=True, exist_ok=True)
    ruta_k.write_text(json.dumps(elegidos, ensure_ascii=False, indent=2, default=str))
    print(f"{len(filas_csv)} filas en {args.salida}; K guardado en {ruta_k}")


if __name__ == "__main__":
    main()
