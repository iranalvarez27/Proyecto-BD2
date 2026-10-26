import heapq
import math
from collections import Counter


class TFIDF:
    def __init__(self, indice):
        self._indice = indice
        self._normas = None

    def idf(self, df: int) -> float:
        return math.log10(self._indice.total_docs() / df)

    def peso(self, tf: int, df: int) -> float:
        return math.log10(1 + tf) * self.idf(df)

    def reiniciar(self) -> None:
        self._normas = None

    def normas(self) -> dict:
        if self._normas is None:
            cuadrados = {}
            for termino in self._indice.terminos():
                df = self._indice.df(termino)
                if df == 0:
                    continue
                for doc_id, tf in self._indice.postings(termino):
                    w = self.peso(tf, df)
                    cuadrados[doc_id] = cuadrados.get(doc_id, 0.0) + w * w
            self._normas = {doc_id: math.sqrt(c) for doc_id, c in cuadrados.items()}
        return self._normas

    def rankear(self, terminos: list, k: int) -> list:
        if k <= 0 or not terminos or self._indice.total_docs() == 0:
            return []

        pesos_q = {}
        for termino, veces in Counter(terminos).items():
            df = self._indice.df(termino)
            if df == 0:
                continue
            pesos_q[termino] = (self.peso(veces, df), df)

        norma_q = math.sqrt(sum(w * w for w, _ in pesos_q.values()))
        if norma_q == 0:
            return []

        normas = self.normas()
        productos = {}
        for termino, (wq, df) in pesos_q.items():
            for doc_id, tf in self._indice.postings(termino):
                productos[doc_id] = productos.get(doc_id, 0.0) + wq * self.peso(tf, df)

        scores = {}
        for doc_id, producto in productos.items():
            norma_d = normas.get(doc_id, 0.0)
            if norma_d > 0 and producto > 0:
                scores[doc_id] = producto / (norma_q * norma_d)

        return heapq.nlargest(k, scores.items(), key=lambda par: par[1])