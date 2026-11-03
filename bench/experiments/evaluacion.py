"""Recall@10 contra el k-NN exacto y medicion de tiempos."""
import time

import numpy as np


def _conjunto(fila) -> set:
    if isinstance(fila, np.ndarray):
        fila = fila.tolist()
    return {x for x in fila if x != -1}


def recall_vs_exacto(resultados, exactos) -> float:
    """Promedio por consulta de cuantos del exacto aparecen en el aproximado, sobre k."""
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


def medir_tiempo(fn, consultas, calentamiento=5):
    """Corre fn(q) por cada consulta, de a una; devuelve (resultados, tiempos en ms)."""
    for q in consultas[:calentamiento]:
        fn(q)
    resultados, tiempos = [], []
    for q in consultas:
        t = time.perf_counter()
        resultados.append(fn(q))
        tiempos.append((time.perf_counter() - t) * 1000)
    return resultados, np.array(tiempos)
