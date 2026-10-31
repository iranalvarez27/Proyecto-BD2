import numpy as np

from index.vector.metricas import distancias


def knn_exacto_lote(consultas, vectores, k: int, metrica: str) -> tuple[np.ndarray, np.ndarray]:
    d = distancias(consultas, vectores, metrica)
    n = d.shape[1]
    k = max(0, min(k, n))
    if k == 0:
        vacio = np.empty((d.shape[0], 0))
        return vacio.astype(np.int64), vacio.astype(np.float32)

    if k < n:
        candidatos = np.argpartition(d, k - 1, axis=1)[:, :k]
    else:
        candidatos = np.broadcast_to(np.arange(n), d.shape)
    orden = np.take_along_axis(d, candidatos, axis=1).argsort(axis=1, kind="stable")
    posiciones = np.take_along_axis(candidatos, orden, axis=1)
    return posiciones, np.take_along_axis(d, posiciones, axis=1)


def knn_exacto(consulta, vectores, k: int, metrica: str) -> list[tuple[int, float]]:
    if np.ndim(consulta) != 1:
        raise ValueError("consulta debe ser un solo vector; para varias usar knn_exacto_lote")
    posiciones, valores = knn_exacto_lote(consulta, vectores, k, metrica)
    return list(zip(posiciones[0].tolist(), valores[0].tolist()))
