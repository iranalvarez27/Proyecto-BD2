import faiss

from index.vector.faiss_base import IndiceFaiss


class HNSW(IndiceFaiss):
    """Grafo HNSW de FAISS (IndexHNSWFlat) para una metrica."""

    def __init__(self, metrica: str, M: int = 16, efConstruction: int = 200, efSearch: int = 16):
        super().__init__(metrica)
        self.M = M
        self.efConstruction = efConstruction
        self.efSearch = efSearch

    def _nuevo(self, dim: int, n: int):
        indice = faiss.IndexHNSWFlat(dim, self.M, self._metrica_faiss)
        indice.hnsw.efConstruction = self.efConstruction
        indice.hnsw.efSearch = self.efSearch
        return indice

    def _parametros(self, efSearch: int | None = None):
        return faiss.SearchParametersHNSW(efSearch=self.efSearch if efSearch is None else efSearch)

    def _config(self) -> dict:
        return {"M": self.M, "efConstruction": self.efConstruction, "efSearch": self.efSearch}
