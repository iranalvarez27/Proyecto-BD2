import json

import numpy as np
import pytest

from index.vector.indices_faiss import IndiceHNSW
from query.conexion import Conexion, ExecutionError, registrar_extractor
from common.types import RID


def _indice(nombre):
    vectores = np.random.default_rng(0).random((5, 4), dtype=np.float32)
    return IndiceHNSW([RID(0, i) for i in range(5)], vectores, rutas=[f'{i}.jpg' for i in range(5)],
                      extractor_nombre=nombre)


def test_el_extractor_se_guarda_con_el_indice(tmp_path):
    ruta = str(tmp_path / 'i.npz')
    _indice('cnn').guardar(ruta)
    assert IndiceHNSW.cargar(ruta).extractor_nombre == 'cnn'


def test_indice_viejo_sin_extractor_es_bovw(tmp_path):
    ruta = str(tmp_path / 'i.npz')
    _indice('bovw').guardar(ruta)
    with np.load(ruta) as f:
        datos = {k: f[k] for k in f.files}
    meta = json.loads(str(datos['meta']))
    del meta['extractor']
    datos['meta'] = np.array(json.dumps(meta))
    np.savez(ruta, **datos)
    assert IndiceHNSW.cargar(ruta).extractor_nombre == 'bovw'


def test_la_conexion_entrega_el_extractor_de_cada_indice():
    conexion = Conexion.__new__(Conexion)
    conexion.extractor = 'extractor bovw'
    registrar_extractor('prueba', 'extractor de prueba')
    assert conexion._extractor_de(_indice('bovw')) == 'extractor bovw'
    assert conexion._extractor_de(_indice('prueba')) == 'extractor de prueba'
    with pytest.raises(ExecutionError):
        conexion._extractor_de(_indice('inexistente'))


def test_similar_to_con_extractor_textual(tmp_path):
    from query.catalog import INDEX_VECTOR
    from text.ingesta import abrir_motor

    def letras(texto, **_):
        return np.array([texto.count(ch) for ch in 'abc'], dtype=np.float32) + 1e-3

    registrar_extractor('letras', letras, texto=True)
    c = abrir_motor(str(tmp_path))
    try:
        for sql in ("CREATE TABLE frases (id INT PRIMARY KEY, texto VARCHAR(40))",
                    "INSERT INTO frases VALUES (1, 'aaa')", "INSERT INTO frases VALUES (2, 'bbb')",
                    "INSERT INTO frases VALUES (3, 'aab')"):
            assert c.execute(sql).ok
        info = c.catalog.get_table('frases')
        registros = list(info.storage.scan_con_rid(info.schema))
        indice = IndiceHNSW([rid for rid, _ in registros], [letras(r.values[1]) for _, r in registros],
                            rutas=[r.values[1] for _, r in registros], extractor_nombre='letras')
        c.catalog.register_index('frases', 'texto', indice, INDEX_VECTOR)
        resultado = c.execute("SELECT id FROM frases WHERE SIMILAR_TO('aaaa', k=2) USING HNSW WITH METRIC=cosine")
        assert resultado.ok, resultado.error
        assert [f[0] if isinstance(f, (list, tuple)) else f['id'] for f in resultado.filas] == [1, 3]
        assert c.execute("INSERT INTO frases VALUES (4, 'cccc')").ok
        resultado = c.execute("SELECT id FROM frases WHERE SIMILAR_TO('cc', k=1) USING HNSW WITH METRIC=cosine")
        assert [f[0] if isinstance(f, (list, tuple)) else f['id'] for f in resultado.filas] == [4]
    finally:
        c.pool.close_all()
