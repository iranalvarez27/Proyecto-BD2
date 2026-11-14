"""Consulta de texto estilo More Like This (Lucene/Elasticsearch) para "descripciones similares".

Se pasa el documento completo por el mismo pipeline del indice, se descartan los terminos
raros en el documento o en la coleccion y se quedan los de mayor peso TF-IDF.
"""
from collections import Counter

from index.tfidf import idf, tf_log
from text.preprocesamiento import normalizar, raiz, stopwords, tokenizar

# valores por defecto del more_like_this de Elasticsearch
MAX_TERMINOS = 25
MIN_TF = 2
MIN_DF = 5


def terminos_relevantes(indice, texto, max_terminos=MAX_TERMINOS, min_tf=MIN_TF, min_df=MIN_DF) -> list[str]:
    """Palabras del texto cuya raiz pesa mas en TF-IDF, de mayor a menor peso.

    Devuelve la palabra original (no la raiz) para que MATCH la vuelva a procesar igual.
    """
    vacias = stopwords(indice.idioma)
    conteo, palabra = Counter(), {}
    for token in tokenizar(normalizar(texto)):
        if token in vacias:
            continue
        termino = raiz(token, indice.idioma) if indice.stemming else token
        conteo[termino] += 1
        palabra.setdefault(termino, token)
    n = indice.total_docs()
    for minimo in (min_tf, 1):
        # un texto corto puede no repetir ningun termino: entonces se acepta tf 1
        pesos = []
        for termino, tf in conteo.items():
            df = indice.df(termino)
            if tf >= minimo and df >= min_df:
                pesos.append((tf_log(tf) * idf(n, df), termino))
        if pesos:
            break
    pesos.sort(key=lambda p: (-p[0], p[1]))
    return [palabra[t] for _, t in pesos[:max_terminos]]
