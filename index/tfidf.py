import heapq
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def idf(n_docs: int, df: int) -> float:
    if n_docs <= 0 or df <= 0:
        return 0.0
    return math.log10(n_docs / df)


def tf_log(tf: int) -> float:
    if tf <= 0:
        return 0.0
    return 1 + math.log10(tf)


def tf_relativo(conteos: dict) -> dict:
    total = sum(conteos.values())
    if total == 0:
        return {}
    return {t: c / total for t, c in conteos.items()}


def vector_tfidf(conteos: dict, idfs: dict, tipo_tf: str = "relativo") -> dict:
    if tipo_tf == "relativo":
        tfs = tf_relativo(conteos)
    elif tipo_tf == "log":
        tfs = {t: tf_log(c) for t, c in conteos.items()}
    else:
        raise ValueError(f"tipo_tf debe ser 'relativo' o 'log', se dio {tipo_tf!r}")
    return {t: tf * idfs[t] for t, tf in tfs.items() if t in idfs}


def norma(vector: dict) -> float:
    return math.sqrt(sum(w * w for w in vector.values()))


def normalizar(vector: dict) -> dict:
    n = norma(vector)
    if n == 0:
        return {}
    return {t: w / n for t, w in vector.items()}


class TFIDF:

    def __init__(self, indice):
        self._indice = indice
        self._normas = None

    def reiniciar(self) -> None:
        self._normas = None

    def normas(self) -> dict[int, float]:
        if self._normas is None:
            cuadrados = {}
            for termino in self._indice.terminos():
                for doc_id, tf in self._indice.postings(termino):
                    w = tf_log(tf)
                    cuadrados[doc_id] = cuadrados.get(doc_id, 0.0) + w * w
            self._normas = {d: math.sqrt(c) for d, c in cuadrados.items()}
        return self._normas

    def rankear(self, terminos: list[str], k: int) -> list[tuple[int, float]]:
        n = self._indice.total_docs()
        if k <= 0 or not terminos or n == 0:
            return []

        pesos_q = {}
        for termino, veces in Counter(terminos).items():
            df = self._indice.df(termino)
            if df == 0:
                continue
            pesos_q[termino] = tf_log(veces) * idf(n, df)

        norma_q = math.sqrt(sum(w * w for w in pesos_q.values()))
        if norma_q == 0:
            return []

        productos = {}
        for termino, wq in pesos_q.items():
            if wq == 0:
                continue
            for doc_id, tf in self._indice.postings(termino):
                productos[doc_id] = productos.get(doc_id, 0.0) + (wq / norma_q) * tf_log(tf)

        normas = self.normas()
        scores = {}
        for doc_id, producto in productos.items():
            norma_d = normas.get(doc_id, 0.0)
            if norma_d > 0:
                scores[doc_id] = producto / norma_d

        return heapq.nlargest(k, scores.items(), key=lambda par: par[1])