import io
import json
import os
import tarfile
from types import SimpleNamespace

import numpy as np
import pytest

from deteccion import biblioteca
from deteccion.detector import Detector, ruta_cache_secuencia
from multimedia import colecciones_audio as ca
from multimedia import config


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    raiz, data = tmp_path / 'raiz', tmp_path / 'data'
    raiz.mkdir()
    data.mkdir()
    monkeypatch.setenv('BD2_DATA_DIR', str(data))
    monkeypatch.setattr(config, 'RAIZ', raiz)
    monkeypatch.setattr(config, 'BASE', tmp_path / 'multimedia')
    return SimpleNamespace(raiz=raiz, data=data, modelo=config.directorio_modelo('audio'), tmp=tmp_path)


def paquete_de_prueba(entorno, nombre='biblioteca.tar.gz'):
    origen = entorno.tmp / 'origen'
    origen.mkdir(exist_ok=True)
    (origen / 'tabla.bin').write_bytes(b'filas')
    (origen / 'meta.json').write_text('{"k": 4}')
    (origen / 'a.mp3').write_bytes(b'mp3')
    manifest = {'version': 1, 'n': 9, 'tabla': 'audios_9', 'pistas': 1, 'creado': '2026-01-01T00:00:00'}
    catalogo = {'audios_9': {'storage': 'heap', 'key_column': 'id', 'archivos': ['audios_9.bin'],
                             'columnas': [], 'indices': []}}
    destino = entorno.tmp / nombre
    biblioteca.crear_paquete(destino, {'data/audios_9.bin': origen / 'tabla.bin',
                                       'modelo/meta.json': origen / 'meta.json',
                                       'audio/bench/data/a.mp3': origen / 'a.mp3'}, manifest, catalogo)
    return destino


def test_paquete_se_instala_en_sus_destinos_fusiona_el_catalogo_y_es_idempotente(entorno):
    (entorno.data / 'catalog.json').write_text(json.dumps({'version': 1, 'tablas': {'otra': {'storage': 'heap'}}}))
    paquete = paquete_de_prueba(entorno)
    biblioteca.instalar_paquete(paquete)
    assert (entorno.data / 'audios_9.bin').read_bytes() == b'filas'
    assert (entorno.modelo / 'meta.json').read_text() == '{"k": 4}'
    assert (entorno.raiz / 'bench/data/a.mp3').read_bytes() == b'mp3'
    tablas = json.loads((entorno.data / 'catalog.json').read_text())['tablas']
    assert set(tablas) == {'otra', 'audios_9'}
    (entorno.data / 'audios_9.bin').unlink()
    biblioteca.instalar_paquete(paquete)
    assert not (entorno.data / 'audios_9.bin').exists()
    biblioteca.instalar_paquete(paquete, forzar=True)
    assert (entorno.data / 'audios_9.bin').exists()
    assert not list(entorno.data.glob('*.part'))


def test_paquete_con_rutas_inseguras_se_rechaza(entorno):
    malo = entorno.tmp / 'malo.tar.gz'
    with tarfile.open(malo, 'w:gz') as tar:
        biblioteca._agregar_bytes(tar, 'manifest.json', json.dumps({'n': 9, 'creado': 'x'}).encode())
        biblioteca._agregar_bytes(tar, 'catalogo.json', b'{}')
        biblioteca._agregar_bytes(tar, 'data/../../fuera.txt', b'no debe escribirse')
    with pytest.raises(ValueError, match='insegura'):
        biblioteca.instalar_paquete(malo)
    assert not (entorno.tmp.parent / 'fuera.txt').exists()
    sin_manifest = entorno.tmp / 'vacio.tar.gz'
    with tarfile.open(sin_manifest, 'w:gz') as tar:
        biblioteca._agregar_bytes(tar, 'data/x', b'x')
    with pytest.raises(ValueError, match='no es un paquete'):
        biblioteca.instalar_paquete(sin_manifest)


def test_huella_depende_del_contenido_y_no_de_fechas_ni_rutas(entorno):
    a, b = entorno.tmp / 'uno.mp3', entorno.tmp / 'otro_sitio.mp3'
    contenido = os.urandom(300_000)
    a.write_bytes(contenido)
    b.write_bytes(contenido)
    os.utime(b, ns=(1, 1))
    assert ca.huella_archivo(a) == ca.huella_archivo(b)
    b.write_bytes(contenido[:-1] + b'\x00' if contenido[-1] else contenido[:-1] + b'\x01')
    assert ca.huella_archivo(a) != ca.huella_archivo(b)


def test_huella_de_un_mp3_ausente_sale_de_huellas_json(entorno):
    ruta = entorno.raiz / 'bench/data/fma/x.mp3'
    with pytest.raises(FileNotFoundError):
        ca.huella_archivo(ruta)
    entorno.modelo.mkdir(parents=True)
    (entorno.modelo / 'huellas.json').write_text(json.dumps({'bench/data/fma/x.mp3': 'abc123'}))
    assert ca.huella_archivo(ruta) == 'abc123'
    assert ca.huella_archivo('/app/bench/data/fma/x.mp3') == 'abc123'


def test_las_huellas_de_varias_bibliotecas_se_acumulan(entorno):
    (entorno.modelo / 'huellas').mkdir(parents=True)
    (entorno.modelo / 'huellas' / 'audios_peru.json').write_text(json.dumps({'bench/data/propia/a.wav': 'huella-a'}))
    (entorno.modelo / 'huellas' / 'audios_fma.json').write_text(json.dumps({'bench/data/fma/b.mp3': 'huella-b'}))
    assert ca.huella_archivo(entorno.raiz / 'bench/data/propia/a.wav') == 'huella-a'
    assert ca.huella_archivo(entorno.raiz / 'bench/data/fma/b.mp3') == 'huella-b'
    (entorno.modelo / 'huellas' / 'audios_otra.json').write_text(json.dumps({'bench/data/fma/c.mp3': 'huella-c'}))
    assert ca.huella_archivo(entorno.raiz / 'bench/data/fma/c.mp3') == 'huella-c'


def test_cache_de_secuencias_es_portable_y_se_invalida_con_el_modelo(tmp_path):
    def modelo(carpeta, norm=b'normalizacion'):
        carpeta.mkdir()
        (carpeta / 'estandarizacion.npz').write_bytes(norm)
        (carpeta / 'meta.json').write_text('{}')
        return SimpleNamespace(directorio=carpeta, meta={'sr': 22050, 'huella_codebook': 'h'})
    a, b = modelo(tmp_path / 'maquina_a'), modelo(tmp_path / 'maquina_b')
    assert ruta_cache_secuencia(a, 'huella-1').name == ruta_cache_secuencia(b, 'huella-1').name
    assert ruta_cache_secuencia(a, 'huella-1').name != ruta_cache_secuencia(a, 'huella-2').name
    c = modelo(tmp_path / 'maquina_c', norm=b'otra normalizacion')
    assert ruta_cache_secuencia(a, 'huella-1').name != ruta_cache_secuencia(c, 'huella-1').name


def test_original_ausente_no_aborta_la_consulta(entorno, monkeypatch):
    import deteccion.detector as modulo
    def sin_archivo(ruta, extractor):
        raise RuntimeError('No se pudo decodificar el audio')
    monkeypatch.setattr(modulo, '_extraer_original', sin_archivo)
    ext = SimpleNamespace(meta={'sr': 10, 'seg_s': 2, 'hop': 1, 'dim': 3})
    detector = Detector(np.ones((1, 3)), [('A', 0)], ext, resolver_original=lambda pid: entorno.raiz / 'no_existe.mp3')
    secuencia = detector._leer_original('A')
    assert secuencia.shape == (0, 3)
    assert detector.originales_ausentes == {'A'}


def test_url_de_originales_puede_apuntar_a_almacenamiento_externo(tmp_path, monkeypatch):
    from backend.audio_detection import url_original
    assert url_original('/app/bench/data/a b.mp3', tmp_path) == '/api/media/bench/data/a%20b.mp3'
    monkeypatch.setenv('MEDIA_BASE_URL', 'https://cdn.ejemplo.org/musica/')
    assert url_original('/app/bench/data/a.mp3', tmp_path) == 'https://cdn.ejemplo.org/musica/bench/data/a.mp3'
    assert url_original('bench/data/../../secreto', tmp_path) is None


def test_modelo_distinto_se_rechaza_y_no_deja_nada_a_medias(entorno):
    entorno.modelo.mkdir(parents=True)
    (entorno.modelo / 'meta.json').write_text('{"k": 999}')
    paquete = paquete_de_prueba(entorno)
    with pytest.raises(ValueError, match='modelo de audio distinto'):
        biblioteca.instalar_paquete(paquete)
    assert not (entorno.data / 'audios_9.bin').exists()
    assert not list(entorno.data.glob('*.part')) and not (entorno.data / 'catalog.json').exists()
    assert (entorno.modelo / 'meta.json').read_text() == '{"k": 999}'
    biblioteca.instalar_paquete(paquete, forzar=True)
    assert (entorno.modelo / 'meta.json').read_text() == '{"k": 4}'


def test_importar_sin_argumentos_usa_la_biblioteca_publicada(monkeypatch):
    llamadas = []
    monkeypatch.setattr(biblioteca, 'importar', lambda *a: llamadas.append(a))
    monkeypatch.delenv('BIBLIOTECA_URL', raising=False)
    monkeypatch.delenv('BIBLIOTECA_SHA256', raising=False)
    biblioteca.main(['importar'])
    assert llamadas == [(biblioteca.URL_POR_DEFECTO, False, biblioteca.SHA256_POR_DEFECTO)]
    llamadas.clear()
    biblioteca.main(['importar', 'otro.tar.gz'])
    assert llamadas == [('otro.tar.gz', False, None)]


def test_atajos_instalan_cada_fuente_por_nombre(monkeypatch):
    llamadas = []
    monkeypatch.setattr(biblioteca, 'importar', lambda *a: llamadas.append(a))
    monkeypatch.delenv('BIBLIOTECA_SHA256', raising=False)
    biblioteca.main(['importar', 'peru', 'fma'])
    assert [c[0] for c in llamadas] == [biblioteca.PUBLICADAS['peru'][0], biblioteca.PUBLICADAS['fma'][0]]
    assert all(c[1] is False for c in llamadas)
