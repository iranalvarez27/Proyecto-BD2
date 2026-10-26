import math
import os
import random
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from common.types import RID
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from index.inverted_store import ArchivoDocumentos, LectorIndice
from index.spimi import construir_spimi, peso_tfidf
from text.preprocesamiento import contar_terminos

DOCUMENTOS_CLASE = [
    "La casa es grande",
    "El gato está en la casa",
    "La casa es bonita y grande",
    "El sol brilla sobre la casa",
]

PALABRAS = ["casa", "perro", "gato", "laptop", "precio", "oferta", "envio", "rapido", "barato", "color",
            "negro", "blanco", "garantia", "bateria", "pantalla", "memoria", "camara", "sonido", "teclado", "raton"]


def _pool() -> BufferPool:
    return BufferPool(FileManager())


def _documentos(textos: list) -> list:
    return [(RID(i // 10, i % 10), texto) for i, texto in enumerate(textos)]


def _indice_esperado(textos: list) -> dict:
    esperado = {}
    for doc_id, texto in enumerate(textos):
        for termino, tf in contar_terminos(texto, "spanish", True).items():
            esperado.setdefault(termino, []).append((doc_id, tf))
    return dict(sorted(esperado.items()))


def _corpus(cantidad: int, semilla: int = 7) -> list:
    azar = random.Random(semilla)
    return [" ".join(azar.choices(PALABRAS, k=azar.randint(3, 15))) for _ in range(cantidad)]


def test_ejemplo_de_clase_en_varios_bloques(tmp_path):
    pool = _pool()
    base = str(tmp_path / "docs")
    estadisticas = construir_spimi(pool, base, _documentos(DOCUMENTOS_CLASE), "spanish", True, max_postings=3)

    assert estadisticas["bloques"] == 3
    assert estadisticas["documentos"] == 4
    lector = LectorIndice(pool, base)
    assert dict(lector.iterar()) == _indice_esperado(DOCUMENTOS_CLASE)
    assert lector.postings("cas") == [(0, 1), (1, 1), (2, 1), (3, 1)]
    assert sorted(os.listdir(tmp_path)) == ["docs.dic", "docs.doc", "docs.pst"]


def test_mismo_indice_con_cualquier_limite_de_bloque(tmp_path):
    textos = _corpus(400)
    esperado = _indice_esperado(textos)
    bloques = []
    for limite in (1, 37, 500, 10_000_000):
        pool = _pool()
        base = str(tmp_path / f"limite{limite}")
        bloques.append(construir_spimi(pool, base, _documentos(textos), "spanish", True, max_postings=limite)["bloques"])
        assert dict(LectorIndice(pool, base).iterar()) == esperado
    assert bloques[0] == 400 and bloques[-1] == 1
    assert bloques == sorted(bloques, reverse=True)


def test_longitudes_y_normas_de_los_documentos(tmp_path):
    pool = _pool()
    base = str(tmp_path / "docs")
    construir_spimi(pool, base, _documentos(DOCUMENTOS_CLASE), "spanish", True, max_postings=2)

    docs = ArchivoDocumentos(pool, base)
    assert docs.N == 4
    assert [docs.longitud(d) for d in range(4)] == [2, 2, 3, 3]
    assert docs.longitud_promedio == pytest.approx(2.5)
    assert docs.rid(3) == RID(0, 3)

    esperado = _indice_esperado(DOCUMENTOS_CLASE)
    for doc_id in range(4):
        pesos = [peso_tfidf(tf, len(p), 4) for p in esperado.values() for d, tf in p if d == doc_id]
        assert docs.norma(doc_id) == pytest.approx(math.sqrt(sum(w * w for w in pesos)))
    assert docs.norma(0) > 0


def test_peso_tfidf_de_clase():
    assert peso_tfidf(1, 1000, 1_000_000) == pytest.approx(math.log10(2) * 3)
    assert peso_tfidf(5, 10, 10) == 0.0
    assert peso_tfidf(0, 3, 10) == 0.0


def test_sin_documentos(tmp_path):
    pool = _pool()
    base = str(tmp_path / "vacio")
    estadisticas = construir_spimi(pool, base, [], "spanish", True)
    assert estadisticas == {"documentos": 0, "bloques": 0, "terminos": 0, "postings": 0}
    assert LectorIndice(pool, base).postings("cas") == []


def test_limite_invalido(tmp_path):
    with pytest.raises(ValueError):
        construir_spimi(_pool(), str(tmp_path / "x"), [], "spanish", True, max_postings=0)


def test_consulta_lee_solo_las_paginas_del_termino(tmp_path):
    base = str(tmp_path / "grande")
    textos = [f"{' '.join(_corpus(1, i)[0].split()[:5])} unico{i:05d}" for i in range(5000)]
    construir_spimi(_pool(), base, _documentos(textos), "spanish", True, max_postings=2000)

    fm = FileManager()
    lector = LectorIndice(BufferPool(fm), base)
    paginas_dic = fm.page_count(base + ".dic") - 1
    assert paginas_dic > 8
    fm.reset_counters()
    assert lector.postings("unico04321") == [(4321, 1)]
    assert fm.reads <= math.ceil(math.log2(paginas_dic)) + 2
