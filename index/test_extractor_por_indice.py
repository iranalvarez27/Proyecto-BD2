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
