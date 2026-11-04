from index.vector.exacto import IndiceExacto
from index.vector.hnsw import HNSW
from index.vector.ivf import IVF


class IndiceVectorialFaiss(IndiceExacto):
    clase_faiss = None
    parametros_por_defecto: dict = {}

    def __init__(self, rids, vectores, extractor=None, resolver=None, rutas=None, **parametros):
        self._parametros = {**self.parametros_por_defecto, **parametros}
        self._faiss = {}
        super().__init__(rids, vectores, extractor, resolver, rutas)

    def _cargar(self, rids, vectores, rutas=None) -> None:
        super()._cargar(rids, vectores, rutas)
        self._faiss = {}

    def _parametros_guardables(self) -> dict:
        return dict(self._parametros)

    def _indice_para(self, metrica: str):
        indice = self._faiss.get(metrica)
        if indice is None:
            indice = self.clase_faiss(metrica, **self._parametros)
            indice.build(self._vectores, self._rids)
            self._faiss[metrica] = indice
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

    def delete(self, key, rid) -> bool:
        borrado = super().delete(key, rid)
        if borrado:
            self._faiss = {}
        return borrado


class IndiceHNSW(IndiceVectorialFaiss):
    metodo = "HNSW"
    clase_faiss = HNSW
    parametros_por_defecto = {"efSearch": 64}


class IndiceIVF(IndiceVectorialFaiss):
    metodo = "IVF"
    clase_faiss = IVF
    parametros_por_defecto = {"nprobe": 8}
