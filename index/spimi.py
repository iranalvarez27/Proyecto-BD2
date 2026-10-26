import heapq
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.buffer_pool import BufferPool
from index.inverted_store import EXT_DOCUMENTOS, ArchivoDocumentos, EscritorIndice, LectorIndice, eliminar
from text.preprocesamiento import contar_terminos

MAX_POSTINGS_POR_BLOQUE = 200_000


def peso_tfidf(tf: int, df: int, n: int) -> float:
    if tf <= 0 or df <= 0:
        return 0.0
    return math.log10(1 + tf) * math.log10(n / df)


def _base_bloque(base: str, numero: int) -> str:
    return f"{base}.bloque{numero}"


def _escribir_bloque(pool: BufferPool, base: str, diccionario: dict) -> None:
    with EscritorIndice(pool, base) as escritor:
        for termino in sorted(diccionario):
            escritor.agregar(termino, diccionario[termino])


def spimi_invert(pool: BufferPool, base: str, documentos, docs: ArchivoDocumentos, idioma: str,
                 stemming: bool, max_postings: int) -> list[str]:
    bloques = []
    diccionario = {}
    postings_en_memoria = 0
    for rid, texto in documentos:
        tf = contar_terminos(texto, idioma, stemming)
        doc_id = docs.agregar(rid, sum(tf.values()))
        for termino, frecuencia in tf.items():
            lista = diccionario.get(termino)
            if lista is None:
                lista = diccionario[termino] = []
            lista.append((doc_id, frecuencia))
        postings_en_memoria += len(tf)
        if postings_en_memoria >= max_postings:
            bloques.append(_base_bloque(base, len(bloques)))
            _escribir_bloque(pool, bloques[-1], diccionario)
            diccionario = {}
            postings_en_memoria = 0
    if diccionario:
        bloques.append(_base_bloque(base, len(bloques)))
        _escribir_bloque(pool, bloques[-1], diccionario)
    docs.guardar()
    return bloques


def mezclar_bloques(pool: BufferPool, bloques: list[str], base: str) -> dict:
    lectores = [LectorIndice(pool, b) for b in bloques]
    iteradores = [l.iterar() for l in lectores]
    cola = []
    for numero, iterador in enumerate(iteradores):
        siguiente = next(iterador, None)
        if siguiente is not None:
            heapq.heappush(cola, (siguiente[0], numero, siguiente[1]))

    with EscritorIndice(pool, base) as escritor:
        while cola:
            termino, numero, postings = heapq.heappop(cola)
            combinada = list(postings)
            pendientes = [numero]
            while cola and cola[0][0] == termino:
                _t, otro, mas = heapq.heappop(cola)
                combinada.extend(mas)
                pendientes.append(otro)
            escritor.agregar(termino, combinada)
            for numero in pendientes:
                siguiente = next(iteradores[numero], None)
                if siguiente is not None:
                    heapq.heappush(cola, (siguiente[0], numero, siguiente[1]))
    return {"terminos": escritor.num_terminos, "postings": escritor.num_postings}


def calcular_normas(lector: LectorIndice, docs: ArchivoDocumentos) -> None:
    n = len(docs)
    suma = [0.0] * n
    for termino, postings in lector.iterar():
        df = len(postings)
        for doc_id, tf in postings:
            suma[doc_id] += peso_tfidf(tf, df, n) ** 2
    docs.guardar_normas(math.sqrt(s) for s in suma)


def construir_spimi(pool: BufferPool, base: str, documentos, idioma: str, stemming: bool,
                    max_postings: int | None = None) -> dict:
    if max_postings is None:
        max_postings = MAX_POSTINGS_POR_BLOQUE
    if max_postings < 1:
        raise ValueError(f"el limite de postings por bloque debe ser positivo: {max_postings}")
    pool.truncate(base + EXT_DOCUMENTOS, 0)
    docs = ArchivoDocumentos(pool, base, idioma=idioma, stemming=stemming)
    bloques = spimi_invert(pool, base, documentos, docs, idioma, stemming, max_postings)
    try:
        totales = mezclar_bloques(pool, bloques, base)
    finally:
        for bloque in bloques:
            eliminar(pool, bloque)
    calcular_normas(LectorIndice(pool, base), docs)
    return {"documentos": len(docs), "bloques": len(bloques), **totales}
