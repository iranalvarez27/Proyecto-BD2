import os

import faiss

from index.vector.exacto import IndiceExacto
from index.vector.faiss_base import _rids_a_array
from index.vector.hnsw import HNSW
from index.vector.ivf import IVF
from index.vector.metricas import METRICAS

METRICA_POR_DEFECTO = "cosine"


class IndiceVectorialFaiss(IndiceExacto):
    clase_faiss = None
    tipo_faiss = None
    parametros_por_defecto: dict = {}

    def __init__(self, rids, vectores, extractor=None, resolver=None, rutas=None, n_coleccion=None,
                 **parametros):
        self._parametros = {**self.parametros_por_defecto, **parametros}
        self._faiss = {}
        # True si los vectores en memoria son los del .npz en disco
        self._en_disco = False
        super().__init__(rids, vectores, extractor, resolver, rutas, n_coleccion)

    def _cargar(self, rids, vectores, rutas=None) -> None:
        super()._cargar(rids, vectores, rutas)
        self._faiss = {}
        self._en_disco = False

    def _parametros_guardables(self) -> dict:
        return dict(self._parametros)

    # un grafo por metrica, en <archivo sin .npz>.<metrica>.faiss

    def _ruta_grafo(self, metrica: str, ruta: str | None = None) -> str:
        return f"{os.path.splitext(ruta or self.archivo)[0]}.{metrica}.faiss"

    def _construir(self, metrica: str):
        indice = self.clase_faiss(metrica, **self._parametros)
        indice.build(self._vectores, self._rids)
        return indice

    def _escribir_grafo(self, metrica: str, indice) -> None:
        ruta = self._ruta_grafo(metrica)
        temporal = ruta + ".tmp"
        faiss.write_index(indice.indice, temporal)
        os.replace(temporal, ruta)

    def _leer_grafos(self) -> None:
        if not self._rids:
            return
        rids = _rids_a_array(self._rids, len(self._rids))
        for metrica in METRICAS:
            ruta = self._ruta_grafo(metrica)
            if not os.path.exists(ruta):
                continue
            indice = self.clase_faiss(metrica, **self._parametros)
            leido = faiss.read_index(ruta)
            if (not isinstance(leido, self.tipo_faiss) or leido.metric_type != indice._metrica_faiss
                    or leido.ntotal != len(self._rids) or leido.d != self._vectores.shape[1]):
                continue
            indice.indice, indice.rids = leido, rids
            self._faiss[metrica] = indice

    def _indice_para(self, metrica: str):
        indice = self._faiss.get(metrica)
        if indice is None:
            indice = self._construir(metrica)
            self._faiss[metrica] = indice
            if self._en_disco:
                self._escribir_grafo(metrica, indice)
        return indice

    def buscar(self, vector, k: int, metrica: str) -> list:
        if not self._rids:
            return []
        return self._indice_para(metrica).search(vector, k)

    def insert(self, key, rid) -> None:
        antes = len(self)
        super().insert(key, rid)
        if len(self) > antes:
            for indice in self._faiss.values():
                indice.agregar(self._vectores[-1:], [rid])
            self._en_disco = False

    def delete(self, key, rid) -> bool:
        borrado = super().delete(key, rid)
        if borrado:
            self._faiss = {}
            self._en_disco = False
        return borrado

    def guardar(self, ruta: str | None = None) -> None:
        ruta = ruta or self.archivo
        if ruta is not None:
            for metrica in METRICAS:
                if os.path.exists(self._ruta_grafo(metrica, ruta)):
                    os.remove(self._ruta_grafo(metrica, ruta))
        super().guardar(ruta)
        if self._rids and METRICA_POR_DEFECTO not in self._faiss:
            self._faiss[METRICA_POR_DEFECTO] = self._construir(METRICA_POR_DEFECTO)
        for metrica, indice in self._faiss.items():
            self._escribir_grafo(metrica, indice)
        self._en_disco = True

    @classmethod
    def cargar(cls, ruta: str):
        indice = super().cargar(ruta)
        indice._leer_grafos()
        indice._en_disco = True
        return indice

    def sincronizar(self, pares) -> dict:
        grafos, en_disco, n = self._faiss, self._en_disco, len(self)
        cambios = super().sincronizar(pares)
        # sin borrados las posiciones viejas no cambian y el grafo se reusa
        if cambios["quitados"] == 0:
            self._faiss = grafos
            if cambios["agregados"]:
                for indice in grafos.values():
                    indice.agregar(self._vectores[n:], self._rids[n:])
            else:
                self._en_disco = en_disco
        return cambios

    def file_paths(self) -> list[str]:
        rutas = super().file_paths()
        if self.archivo is not None:
            rutas += [r for r in (self._ruta_grafo(m) for m in METRICAS) if os.path.exists(r)]
        return rutas


class IndiceHNSW(IndiceVectorialFaiss):
    metodo = "HNSW"
    clase_faiss = HNSW
    tipo_faiss = faiss.IndexHNSWFlat
    parametros_por_defecto = {"efSearch": 64}


class IndiceIVF(IndiceVectorialFaiss):
    metodo = "IVF"
    clase_faiss = IVF
    tipo_faiss = faiss.IndexIVFFlat
    parametros_por_defecto = {"nprobe": 8}
