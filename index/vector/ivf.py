import math

import faiss

from index.vector.faiss_base import IndiceFaiss


class IVF(IndiceFaiss):
    """IVF de FAISS (IndexIVFFlat): K-Means en nlist listas, se recorren nprobe."""

    def __init__(self, metrica: str, nlist: int | None = None, nprobe: int = 1, semilla: int = 42):
        super().__init__(metrica)
        self.nlist_pedido = nlist
        self.nprobe = nprobe
        self.semilla = semilla

    @property
    def nlist(self) -> int:
        return self.indice.nlist

    def _nuevo(self, dim: int, n: int):
        nlist = self.nlist_pedido or max(1, round(math.sqrt(n)))
        if nlist > n:
            raise ValueError(f"nlist={nlist} es mayor que la cantidad de vectores ({n})")
        if self.metrica == "euclidean":
            cuantizador = faiss.IndexFlatL2(dim)
        else:
            cuantizador = faiss.IndexFlatIP(dim)
        indice = faiss.IndexIVFFlat(cuantizador, dim, nlist, self._metrica_faiss)
        indice.cp.seed = self.semilla
        # solo apaga el aviso de FAISS cuando hay menos de 39 puntos por lista
        indice.cp.min_points_per_centroid = 1
        indice.nprobe = self.nprobe
        return indice

    def _parametros(self, nprobe: int | None = None):
        return faiss.SearchParametersIVF(nprobe=self.nprobe if nprobe is None else nprobe)

    def _config(self) -> dict:
        return {"nlist": self.nlist_pedido, "nprobe": self.nprobe, "semilla": self.semilla}
