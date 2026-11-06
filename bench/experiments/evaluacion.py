import os
import time
from pathlib import Path

import numpy as np


def _conjunto(fila) -> set:
    if isinstance(fila, np.ndarray):
        fila = fila.tolist()
    return {x for x in fila if x != -1}


def recall_vs_exacto(resultados, exactos) -> float:
    if len(resultados) != len(exactos):
        raise ValueError(f"hay {len(resultados)} resultados y {len(exactos)} exactos")
    recalls = []
    for aprox, exacto in zip(resultados, exactos):
        e = _conjunto(exacto)
        if e:
            recalls.append(len(_conjunto(aprox) & e) / len(e))
    if not recalls:
        raise ValueError("no hay consultas con vecinos exactos")
    return float(np.mean(recalls))


def precision_at_k(recuperados, relevantes: set, k: int = 10) -> float:
    if k <= 0:
        return 0.0
    top_k = list(recuperados)[:k]
    if not top_k:
        return 0.0
    aciertos = sum(1 for doc_id in top_k if doc_id in relevantes)
    return float(aciertos) / float(k)


def recall_at_k(recuperados, relevantes: set, k: int = 10) -> float:
    if not relevantes or k <= 0:
        return 0.0
    top_k = set(list(recuperados)[:k])
    aciertos = len(top_k & set(relevantes))
    return float(aciertos) / float(len(relevantes))


def tamano_archivos_mb(rutas) -> float:
    total_bytes = 0
    for r in rutas:
        p = Path(r)
        if p.exists() and p.is_file():
            total_bytes += os.path.getsize(p)
    return total_bytes / (1024.0 * 1024.0)


def medir_tiempo(fn, consultas, calentamiento=5):
    for q in consultas[:calentamiento]:
        fn(q)
    resultados, tiempos = [], []
    for q in consultas:
        t = time.perf_counter()
        resultados.append(fn(q))
        tiempos.append((time.perf_counter() - t) * 1000)
    return resultados, np.array(tiempos)

