import numpy as np

from index.vector.base import IndiceVectorial
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


class IndiceExacto(IndiceVectorial):
    metodo = "EXACTO"

    def __init__(self, rids, vectores, extractor=None, resolver=None):
        self._extractor = extractor
        self._resolver = resolver
        self._cargar(rids, vectores)

    def _cargar(self, rids, vectores) -> None:
        self._rids = list(rids)
        if self._rids:
            self._vectores = np.asarray(vectores, dtype=np.float32).reshape(len(self._rids), -1)
        else:
            self._vectores = np.empty((0, 0), dtype=np.float32)

    def __len__(self) -> int:
        return len(self._rids)

    def extraer(self, ruta: str):
        if self._extractor is None:
            raise ValueError("el indice no tiene un extractor de caracteristicas")
        return np.asarray(self._extractor(ruta), dtype=np.float32)

    def _vector_de(self, ruta):
        return self.extraer(self._resolver(ruta) if self._resolver is not None else ruta)

    def buscar(self, vector, k: int, metrica: str) -> list:
        if not self._rids:
            return []
        return [(self._rids[i], d) for i, d in knn_exacto(vector, self._vectores, k, metrica)]

    def insert(self, key, rid) -> None:
        vector = self._vector_de(key)
        if self._rids:
            self._vectores = np.vstack([self._vectores, vector[None, :]])
        else:
            self._vectores = vector[None, :].copy()
        self._rids.append(rid)

    def delete(self, key, rid) -> bool:
        if rid not in self._rids:
            return False
        i = self._rids.index(rid)
        self._rids.pop(i)
        self._vectores = np.delete(self._vectores, i, axis=0)
        return True

    def bulk_load(self, pairs) -> None:
        pairs = list(pairs)
        self._cargar([rid for _ruta, rid in pairs], [self._vector_de(ruta) for ruta, _rid in pairs])
