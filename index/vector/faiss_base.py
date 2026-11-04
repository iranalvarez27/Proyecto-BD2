import json

import faiss
import numpy as np

from common.types import RID
from index.vector.metricas import normas, validar_metrica


def _matriz(vectores) -> np.ndarray:
    x = np.ascontiguousarray(vectores, dtype=np.float32)
    if x.ndim == 1:
        x = x[None, :]
    if x.ndim != 2:
        raise ValueError(f"se esperaba un vector o una matriz, se dio ndim={x.ndim}")
    return x


def _rids_a_array(rids, n: int) -> np.ndarray:
    pares = np.array([(r.page_id, r.slot_id) for r in rids], dtype=np.int64).reshape(-1, 2)
    if len(pares) != n:
        raise ValueError(f"hay {n} vectores y {len(pares)} rids")
    return pares


class IndiceFaiss:
    """Base de HNSW e IVF: FAISS guarda posiciones 0..N-1 y aca se traducen a RID."""

    def __init__(self, metrica: str):
        validar_metrica(metrica)
        self.metrica = metrica
        self.indice = None
        self.rids = None

    def _nuevo(self, dim: int, n: int):
        raise NotImplementedError

    def _parametros(self, **kw):
        raise NotImplementedError

    def _config(self) -> dict:
        raise NotImplementedError

    @property
    def _metrica_faiss(self) -> int:
        return faiss.METRIC_L2 if self.metrica == "euclidean" else faiss.METRIC_INNER_PRODUCT

    def __len__(self) -> int:
        return 0 if self.indice is None else self.indice.ntotal

    @property
    def dim(self) -> int:
        return self.indice.d

    def _preparar(self, vectores) -> np.ndarray:
        x = _matriz(vectores)
        if self.indice is not None and x.shape[1] != self.indice.d:
            raise ValueError(f"dimension distinta: indice {self.indice.d}, se dio {x.shape[1]}")
        if self.metrica == "cosine":
            n = normas(x)[:, None]
            x = np.divide(x, n, out=np.zeros_like(x), where=n > 0)
        return x

    def _a_distancia(self, d: np.ndarray) -> np.ndarray:
        if self.metrica == "euclidean":
            return np.sqrt(np.maximum(d, 0))
        if self.metrica == "cosine":
            return np.clip(1 - d, 0, 2)
        return -d

    def build(self, vectores, rids=None) -> None:
        self.indice = None
        x = self._preparar(vectores)
        if len(x) == 0:
            raise ValueError("no hay vectores para construir el indice")
        pares = None if rids is None else _rids_a_array(rids, len(x))
        indice = self._nuevo(x.shape[1], len(x))
        if not indice.is_trained:
            indice.train(x)
        indice.add(x)
        self.indice, self.rids = indice, pares

    def agregar(self, vectores, rids=None) -> None:
        if self.indice is None:
            raise RuntimeError("el indice no esta construido")
        if (rids is None) != (self.rids is None):
            raise ValueError("el indice se construyo " + ("sin" if self.rids is None else "con") + " rids")
        x = self._preparar(vectores)
        self.indice.add(x)
        if rids is not None:
            self.rids = np.vstack([self.rids, _rids_a_array(rids, len(x))])

    def search_lote(self, consultas, k: int, **kw) -> tuple[np.ndarray, np.ndarray]:
        """Posiciones y distancias nq x k; donde no hay vecino la posicion es -1."""
        if self.indice is None:
            raise RuntimeError("el indice no esta construido")
        q = self._preparar(consultas)
        if k <= 0:
            vacio = np.empty((len(q), 0))
            return vacio.astype(np.int64), vacio.astype(np.float32)
        d, pos = self.indice.search(q, k, params=self._parametros(**kw))
        d = self._a_distancia(d)
        d[pos < 0] = np.inf
        return pos, d

    def search(self, consulta, k: int, **kw) -> list[tuple]:
        """[(rid, distancia)] de menor a mayor; sin rids devuelve posiciones."""
        if np.ndim(consulta) != 1:
            raise ValueError("consulta debe ser un solo vector; para varias usar search_lote")
        pos, d = self.search_lote(consulta, k, **kw)
        res = []
        for p, dist in zip(pos[0].tolist(), d[0].tolist()):
            if p < 0:
                continue
            res.append((p if self.rids is None else RID(*self.rids[p].tolist()), dist))
        return res

    def save(self, ruta: str) -> None:
        if self.indice is None:
            raise RuntimeError("el indice no esta construido")
        faiss.write_index(self.indice, ruta)
        meta = {"tipo": type(self).__name__, "metrica": self.metrica, "config": self._config()}
        rids = np.empty((0, 2), np.int64) if self.rids is None else self.rids
        np.savez(ruta + ".meta.npz", meta=np.array(json.dumps(meta)), rids=rids,
                 con_rids=np.array(self.rids is not None))

    @classmethod
    def load(cls, ruta: str):
        with np.load(ruta + ".meta.npz") as f:
            meta = json.loads(str(f["meta"]))
            rids = f["rids"] if bool(f["con_rids"]) else None
        if meta["tipo"] != cls.__name__:
            raise ValueError(f"{ruta} es un {meta['tipo']}, no un {cls.__name__}")
        obj = cls(meta["metrica"], **meta["config"])
        obj.indice = faiss.read_index(ruta)
        obj.rids = rids
        return obj
