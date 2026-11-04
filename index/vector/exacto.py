import json
import os

import numpy as np

from common.types import RID

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

    def __init__(self, rids, vectores, extractor=None, resolver=None, rutas=None):
        self._extractor = extractor
        self._resolver = resolver
        self.archivo = None
        self.sincronizado = True
        self._cargar(rids, vectores, rutas)

    def _cargar(self, rids, vectores, rutas=None) -> None:
        self._rids = list(rids)
        self._rutas = [None] * len(self._rids) if rutas is None else list(rutas)
        self._pares = set(zip(self._rutas, self._rids))
        if self._rids:
            self._vectores = np.asarray(vectores, dtype=np.float32).reshape(len(self._rids), -1)
        else:
            self._vectores = np.empty((0, 0), dtype=np.float32)

    def __len__(self) -> int:
        return len(self._rids)

    def configurar(self, extractor, resolver) -> None:
        if extractor is not None:
            self._extractor = extractor
        if resolver is not None:
            self._resolver = resolver

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
        if (key, rid) in self._pares:
            return
        vector = self._vector_de(key)
        if self._rids:
            self._vectores = np.vstack([self._vectores, vector[None, :]])
        else:
            self._vectores = vector[None, :].copy()
        self._rids.append(rid)
        self._rutas.append(key)
        self._pares.add((key, rid))

    def delete(self, key, rid) -> bool:
        if rid not in self._rids:
            return False
        i = self._rids.index(rid)
        self._rids.pop(i)
        self._pares.discard((self._rutas.pop(i), rid))
        self._vectores = np.delete(self._vectores, i, axis=0)
        return True

    def bulk_load(self, pairs) -> None:
        pairs = list(pairs)
        self._cargar([rid for _ruta, rid in pairs], [self._vector_de(ruta) for ruta, _rid in pairs],
                     [ruta for ruta, _rid in pairs])
        self.sincronizado = True

    def file_paths(self) -> list[str]:
        return [] if self.archivo is None else [self.archivo]

    # persistencia: se guardan los vectores, los RID y la ruta de cada archivo; los grafos de FAISS se rearman al consultar

    def _parametros_guardables(self) -> dict:
        return {}

    def guardar(self, ruta: str | None = None) -> None:
        ruta = ruta or self.archivo
        if ruta is None:
            raise ValueError("el indice no tiene una ruta de archivo")
        rids = np.array([(r.page_id, r.slot_id) for r in self._rids], dtype=np.int64).reshape(-1, 2)
        meta = {"metodo": self.metodo, "parametros": self._parametros_guardables()}
        temporal = ruta + ".tmp.npz"
        np.savez(temporal, vectores=self._vectores, rids=rids, rutas=np.array(self._rutas, dtype=str),
                 meta=np.array(json.dumps(meta)))
        os.replace(temporal, ruta)
        self.archivo = ruta

    @classmethod
    def cargar(cls, ruta: str):
        with np.load(ruta) as f:
            meta = json.loads(str(f["meta"]))
            vectores, rids, rutas = f["vectores"], f["rids"], f["rutas"].tolist()
        if meta["metodo"] != cls.metodo:
            raise ValueError(f"{ruta} es un indice {meta['metodo']}, no {cls.metodo}")
        indice = cls([RID(int(p), int(s)) for p, s in rids], vectores, rutas=rutas, **meta["parametros"])
        indice.archivo = ruta
        indice.sincronizado = False
        return indice

    def sincronizar(self, pares) -> dict:
        actuales = set(pares)
        guardados = self._pares
        nuevos = [(ruta, rid) for ruta, rid in pares if (ruta, rid) not in guardados]
        vectores_nuevos = [self._vector_de(ruta) for ruta, _rid in nuevos]
        conservar = [i for i, par in enumerate(zip(self._rutas, self._rids)) if par in actuales]
        quitados = len(self._rids) - len(conservar)
        rids = [self._rids[i] for i in conservar] + [rid for _ruta, rid in nuevos]
        rutas = [self._rutas[i] for i in conservar] + [ruta for ruta, _rid in nuevos]
        base = self._vectores[conservar] if conservar else np.empty((0, 0), dtype=np.float32)
        if vectores_nuevos:
            nuevos_np = np.asarray(vectores_nuevos, dtype=np.float32)
            todos = nuevos_np if len(base) == 0 else np.vstack([base, nuevos_np])
        else:
            todos = base
        self._cargar(rids, todos, rutas)
        self.sincronizado = True
        return {"agregados": len(nuevos), "quitados": quitados}
