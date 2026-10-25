import heapq
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BM25:
    def __init__(self, indice, k1: float = 1.5, b: float = 0.75):
        if k1 < 0:
            raise ValueError(f"k1 debe ser >= 0, se dio {k1}")
        if not (0 <= b <= 1):
            raise ValueError(f"b debe estar entre 0 y 1, se dio {b}")
        self._indice = indice
        self._k1 = k1
        self._b = b

    def idf(self, df: int) -> float:
        n = self._indice.total_docs()
        return math.log((n-df+ 0.5)/(df+0.5)+1)

    def rankear(self, terminos: list[str], k: int) -> list[tuple[int, float]]:
        if k <= 0 or not terminos:
            return []
        avgdl = self._indice.longitud_promedio()
        if self._indice.total_docs() == 0 or avgdl == 0:
            return []

        scores = {}
        for termino in dict.fromkeys(terminos):
            df = self._indice.df(termino)
            if df == 0:
                continue
            idf = self.idf(df)
            for doc_id, tf in self._indice.postings(termino):
                largo = self._indice.longitud_doc(doc_id)
                norma = self._k1 * (1 - self._b + self._b * largo / avgdl)
                parcial = idf * tf * (self._k1 + 1) / (tf + norma)
                scores[doc_id] = scores.get(doc_id, 0.0) + parcial

        return heapq.nlargest(k, scores.items(), key=lambda par: par[1])