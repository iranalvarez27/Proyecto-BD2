import heapq
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from common.types import RID
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from index.inverted_store import (DOCUMENTOS_POR_PAGINA, POSTINGS_POR_PAGINA, ArchivoDocumentos,
                                  EscritorIndice, LectorIndice, eliminar, rutas)

EJEMPLO_CLASE = {
    "casa": [(1, 1), (2, 1), (3, 2), (4, 1)],
    "grande": [(1, 1), (3, 2)],
    "gato": [(2, 1)],
    "bonita": [(3, 1)],
    "sol": [(1, 2), (4, 2)],
    "brilla": [(4, 3)],
}


def _pool() -> BufferPool:
    return BufferPool(FileManager())


def _escribir(pool, base, indice: dict) -> None:
    with EscritorIndice(pool, base) as escritor:
        for termino, postings in sorted(indice.items()):
            escritor.agregar(termino, postings)


def test_ejemplo_indice_invertido_de_clase(tmp_path):
    pool = _pool()
    base = str(tmp_path / "docs_contenido")
    _escribir(pool, base, EJEMPLO_CLASE)

    lector = LectorIndice(pool, base)
    assert len(lector) == 6
    assert lector.num_postings == 11
    assert lector.postings("casa") == [(1, 1), (2, 1), (3, 2), (4, 1)]
    assert lector.df("casa") == 4
    assert lector.df("brilla") == 1
    assert "sol" in lector
    assert lector.postings("perro") == []
    assert lector.df("perro") == 0
    assert "aaa" not in lector and "zzz" not in lector
    assert [t for t, _ in lector.iterar()] == sorted(EJEMPLO_CLASE)
    assert dict(lector.terminos()) == {t: len(p) for t, p in EJEMPLO_CLASE.items()}


def test_diccionario_y_postings_en_varias_paginas(tmp_path):
    pool = _pool()
    base = str(tmp_path / "grande")
    indice = {f"termino{i:05d}": [(d, d % 7 + 1) for d in range(i % 5 + 1)] for i in range(3000)}
    indice["mmm_frecuente"] = [(d, 1) for d in range(3 * POSTINGS_POR_PAGINA + 10)]
    _escribir(pool, base, indice)

    assert pool.page_count(base + ".dic") > 2
    assert pool.page_count(base + ".pst") > 4
    lector = LectorIndice(pool, base)
    assert len(lector) == len(indice)
    for termino in ("termino00000", "termino01499", "termino02999", "mmm_frecuente"):
        assert lector.postings(termino) == indice[termino]
    assert lector.postings("termino03000") == []
    assert list(lector.iterar()) == sorted(indice.items())


def test_indice_persiste_al_reabrir(tmp_path):
    base = str(tmp_path / "persistente")
    pool = _pool()
    _escribir(pool, base, EJEMPLO_CLASE)
    pool.close_all()

    lector = LectorIndice(_pool(), base)
    assert lector.postings("sol") == [(1, 2), (4, 2)]
    assert len(lector) == 6


def test_reescribir_reemplaza_el_indice(tmp_path):
    pool = _pool()
    base = str(tmp_path / "rehecho")
    _escribir(pool, base, EJEMPLO_CLASE)
    _escribir(pool, base, {"nuevo": [(0, 5)]})

    lector = LectorIndice(pool, base)
    assert len(lector) == 1
    assert lector.postings("nuevo") == [(0, 5)]
    assert lector.postings("casa") == []


def test_validaciones_del_escritor(tmp_path):
    pool = _pool()
    escritor = EscritorIndice(pool, str(tmp_path / "malo"))
    escritor.agregar("beta", [(1, 1)])
    with pytest.raises(ValueError):
        escritor.agregar("alfa", [(1, 1)])
    with pytest.raises(ValueError):
        escritor.agregar("beta", [(2, 1)])
    with pytest.raises(ValueError):
        escritor.agregar("gamma", [])
    with pytest.raises(ValueError):
        escritor.agregar("gamma", [(3, 1), (2, 1)])
    with pytest.raises(ValueError):
        escritor.agregar("gamma", [(1, 0)])
    with pytest.raises(ValueError):
        escritor.agregar("x" * 256, [(1, 1)])


def test_lector_sin_indice(tmp_path):
    with pytest.raises(FileNotFoundError):
        LectorIndice(_pool(), str(tmp_path / "no_existe"))


def test_bloques_con_el_mismo_formato_se_pueden_mezclar(tmp_path):
    pool = _pool()
    bloque1 = {"casa": [(1, 1), (2, 1)], "gato": [(2, 1)], "grande": [(1, 1)]}
    bloque2 = {"brilla": [(4, 3)], "casa": [(3, 2), (4, 1)], "sol": [(4, 2)]}
    _escribir(pool, str(tmp_path / "bloque1"), bloque1)
    _escribir(pool, str(tmp_path / "bloque2"), bloque2)

    lectores = [LectorIndice(pool, str(tmp_path / f"bloque{i}")) for i in (1, 2)]
    mezclado = {}
    for termino, postings in heapq.merge(*(l.iterar() for l in lectores), key=lambda e: e[0]):
        mezclado.setdefault(termino, []).extend(postings)
    _escribir(pool, str(tmp_path / "final"), mezclado)

    final = LectorIndice(pool, str(tmp_path / "final"))
    assert final.postings("casa") == [(1, 1), (2, 1), (3, 2), (4, 1)]
    assert len(final) == 5


def test_archivo_de_documentos(tmp_path):
    base = str(tmp_path / "docs")
    pool = _pool()
    docs = ArchivoDocumentos(pool, base, idioma="spanish")
    total = 2 * DOCUMENTOS_POR_PAGINA + 17
    for i in range(total):
        assert docs.agregar(RID(i // 10, i % 10), i % 9 + 1) == i
    assert len(docs) == total
    assert docs.rid(total - 1) == RID((total - 1) // 10, (total - 1) % 10)
    docs.guardar()

    longitudes = [i % 9 + 1 for i in range(total)]
    docs.guardar_normas([float(i) / 2 for i in range(total)])
    pool.close_all()

    reabierto = ArchivoDocumentos(_pool(), base)
    assert reabierto.N == total
    assert reabierto.idioma == "spanish" and reabierto.stemming is True
    assert reabierto.longitud(DOCUMENTOS_POR_PAGINA) == longitudes[DOCUMENTOS_POR_PAGINA]
    assert reabierto.longitud_promedio == pytest.approx(sum(longitudes) / total)
    assert reabierto.norma(total - 1) == pytest.approx((total - 1) / 2)
    assert [d for d, *_ in reabierto.iterar()] == list(range(total))


def test_documentos_se_pueden_agregar_despues_de_guardar(tmp_path):
    pool = _pool()
    docs = ArchivoDocumentos(pool, str(tmp_path / "docs"), idioma="english", stemming=False)
    docs.agregar(RID(0, 0), 3)
    docs.guardar()
    docs.agregar(RID(0, 1), 5)
    assert docs.longitud(1) == 5
    docs.guardar()
    assert [(d, r, l) for d, r, l, _ in docs.iterar()] == [(0, RID(0, 0), 3), (1, RID(0, 1), 5)]
    assert docs.longitud_promedio == 4
    with pytest.raises(IndexError):
        docs.longitud(2)


def test_documentos_nuevos_necesitan_idioma(tmp_path):
    with pytest.raises(ValueError):
        ArchivoDocumentos(_pool(), str(tmp_path / "docs"))


def test_eliminar_borra_los_tres_archivos(tmp_path):
    pool = _pool()
    base = str(tmp_path / "borrable")
    _escribir(pool, base, EJEMPLO_CLASE)
    ArchivoDocumentos(pool, base, idioma="spanish").guardar()
    assert all(os.path.exists(r) for r in rutas(base))
    eliminar(pool, base)
    assert not any(os.path.exists(r) for r in rutas(base))
