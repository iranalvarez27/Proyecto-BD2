from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from backend.audio_detection import crear_router, resolver_subida, url_original


def test_rutas_de_subida_no_permiten_salir_del_directorio(tmp_path):
    uploads = tmp_path / 'data' / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'q.wav').write_bytes(b'wave')
    assert resolver_subida(tmp_path, 'uploads/q.wav') == uploads / 'q.wav'
    (tmp_path / 'data' / 'fuera.wav').write_bytes(b'wave')
    for ruta in ['fuera.wav', 'uploads/../fuera.wav', str(tmp_path / 'data' / 'fuera.wav')]:
        with pytest.raises(ValueError):
            resolver_subida(tmp_path, ruta)
    assert url_original('/app/bench/data/a.mp3', tmp_path) == '/api/media/bench/data/a.mp3'
    assert url_original('bench/data/../../secreto', tmp_path) is None


def test_api_consume_metadata_sql_y_devuelve_timeline(tmp_path, monkeypatch):
    from backend import audio_detection as api
    uploads = tmp_path / 'data' / 'uploads'
    uploads.mkdir(parents=True)
    (uploads / 'q.wav').write_bytes(b'wave')
    queries = []
    def query(sql):
        queries.append(sql)
        return dict(status='success', columns=['track_id', 'segmento', 'titulo', 'artista', 'genero', 'ruta'],
                    rows=[[7, i, 'Original', 'Artista', 'Rock', '/app/bench/data/a.mp3'] for i in range(3)])
    archivo_meta = tmp_path / 'tabla_audio.bin'
    archivo_meta.write_bytes(b'datos originales')
    storage = SimpleNamespace(file_paths=lambda: [archivo_meta])
    engine = SimpleNamespace(catalog=SimpleNamespace(existe_tabla=lambda t: t == 'audios_10k',
                             get_table=lambda t: SimpleNamespace(storage=storage)),
                             execute_query=query, data_revision=0, data_dir=tmp_path)
    tiempos = np.arange(0, 3.1, .5)
    ext = SimpleNamespace(meta={'sr': 10, 'seg_s': 2, 'hop': 1},
                          vectores_senal=lambda y, p: (tiempos, np.tile([1., 0.], (7, 1))),
                          _descriptores_audio=lambda y: np.stack((np.sin(np.arange(len(y))), np.cos(np.arange(len(y)))), axis=1))
    monkeypatch.setattr(api.bovw, '_extractor', lambda *a: ext)
    monkeypatch.setattr(api.bovw, 'cargar_coleccion', lambda *a: (np.array([[1., 0.]] * 3), [('7', i) for i in range(3)]))
    monkeypatch.setattr(api, 'cargar_audio', lambda *a: np.ones(50))
    monkeypatch.setattr('multimedia.mfcc.cargar_audio', lambda *a: np.ones(50))
    app = FastAPI()
    app.include_router(crear_router(engine, tmp_path))
    client = TestClient(app)
    response = client.post('/api/audio/detect', json={'path': 'uploads/q.wav'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['coincidencias'][0]['titulo'] == 'Original'
    assert data['coincidencias'][0]['artista'] == 'Artista'
    assert data['tabla'] == 'audios_10k' and queries
    assert not data['metricas']['metadata_cache']
    assert data['metricas']['metadata_origen'] == 'sql'
    def cliente_nuevo():
        app_nueva = FastAPI()
        app_nueva.include_router(crear_router(engine, tmp_path))
        return TestClient(app_nueva)
    reiniciada = cliente_nuevo().post('/api/audio/detect', json={'path': 'uploads/q.wav'}).json()
    assert reiniciada['metricas']['metadata_origen'] == 'disco' and len(queries) == 1
    assert reiniciada['coincidencias'] == data['coincidencias']
    import json
    snapshot_path = tmp_path / 'cache_audio/audios_10k.json'
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    snapshot['segmentos'] = snapshot['segmentos'][:-1]
    snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
    corregida = cliente_nuevo().post('/api/audio/detect', json={'path': 'uploads/q.wav'})
    assert corregida.status_code == 200, corregida.text
    assert corregida.json()['metricas']['metadata_origen'] == 'sql'
    assert len(queries) == 2
    (tmp_path / 'cache_audio/audios_10k.json').write_text('[]', encoding='utf-8')
    recuperada = cliente_nuevo().post('/api/audio/detect', json={'path': 'uploads/q.wav'}).json()
    assert recuperada['metricas']['metadata_origen'] == 'sql' and len(queries) == 3
    repetida = client.post('/api/audio/detect', json={'path': 'uploads/q.wav'}).json()
    assert repetida['metricas']['metadata_cache'] and len(queries) == 3
    assert repetida['coincidencias'] == data['coincidencias']
    engine.data_revision += 1
    actualizada = client.post('/api/audio/detect', json={'path': 'uploads/q.wav'}).json()
    assert not actualizada['metricas']['metadata_cache'] and len(queries) == 4
    archivo_meta.write_bytes(b'otro proceso reemplazo estos datos')
    externa = client.post('/api/audio/detect', json={'path': 'uploads/q.wav'}).json()
    assert not externa['metricas']['metadata_cache'] and len(queries) == 5
    assert client.post('/api/audio/detect', json={'path': '../q.wav'}).status_code == 400
    assert client.post('/api/audio/detect', json={'path': 'uploads/q.wav', 'segmento_s': 2}).status_code == 422
    assert client.post('/api/audio/detect', json={'path': 'uploads/q.wav', 'metodo': 'BAD'}).status_code == 400
    assert client.post('/api/audio/detect', json={'path': 'uploads/q.wav', 'n_coleccion': 999}).status_code == 400


def test_colecciones_recarga_y_muestra_coleccion_completa(tmp_path, monkeypatch):
    import json
    from backend import audio_detection as api
    from query import catalog_store
    carpeta = tmp_path / 'colecciones'
    (carpeta / '115123').mkdir(parents=True)
    (carpeta / '115123' / 'coleccion.json').write_text(json.dumps({
        'alcance': 'todas_fma_small', 'canciones': 7997}), encoding='utf-8')
    conocidas = set()
    llamadas = []
    def cargar(catalog, pool, data_dir):
        llamadas.append(data_dir)
        conocidas.add('audios_115123')
    engine = SimpleNamespace(data_dir=str(tmp_path), pool=object(),
                             catalog=SimpleNamespace(existe_tabla=lambda t: t in conocidas))
    monkeypatch.setattr(catalog_store, 'cargar', cargar)
    monkeypatch.setattr(api.config, 'directorio_colecciones', lambda tipo: carpeta)
    app = FastAPI()
    app.include_router(crear_router(engine, tmp_path))
    datos = TestClient(app).get('/api/audio/collections').json()
    assert llamadas == [str(tmp_path)]
    coleccion, = datos['colecciones']
    assert coleccion['n'] == 115123 and coleccion['tabla'] == 'audios_115123'
    assert coleccion['canciones'] == 7997 and coleccion['completa']
    assert coleccion['nombre'] == 'FMA · catálogo completo'


def test_coleccion_propia_se_identifica_y_piloto_no_se_marca_completo(tmp_path, monkeypatch):
    import json
    from backend import audio_detection as api
    for n, alcance, canciones in [(1155, 'musica_propia_piloto', 10), (54000, 'musica_propia', 500)]:
        carpeta = tmp_path / str(n)
        carpeta.mkdir()
        (carpeta / 'coleccion.json').write_text(json.dumps({
            'alcance': alcance, 'nombre': 'Música propia', 'canciones': canciones}), encoding='utf-8')
    monkeypatch.setattr(api.config, 'directorio_colecciones', lambda tipo, base=None: tmp_path)
    engine = SimpleNamespace(catalog=SimpleNamespace(existe_tabla=lambda t: True))
    app = FastAPI()
    app.include_router(crear_router(engine, tmp_path))
    client = TestClient(app)
    assert len(client.get('/api/audio/collections').json()['colecciones']) == 1
    datos = client.get('/api/audio/collections?incluir_auxiliares=true').json()['colecciones']
    assert [c['completa'] for c in datos] == [False, True]
    assert all(c['propia'] and c['nombre'].startswith('Perú e internacional') for c in datos)


def test_biblioteca_es_unica_opcion_predeterminada_y_resuelve_tabla_estable(tmp_path, monkeypatch):
    import json
    from backend import audio_detection as api
    for n, info in [(10000, {}), (170002, {'alcance': 'biblioteca_musical',
                           'tabla': 'audio_segmentos', 'canciones': 8494})]:
        carpeta = tmp_path / str(n)
        carpeta.mkdir()
        (carpeta / 'coleccion.json').write_text(json.dumps(info), encoding='utf-8')
    monkeypatch.setattr(api.config, 'directorio_colecciones', lambda tipo, base=None: tmp_path)
    engine = SimpleNamespace(catalog=SimpleNamespace(existe_tabla=lambda t: t in {'audios_10k', 'audio_segmentos'}))
    app = FastAPI()
    app.include_router(crear_router(engine, tmp_path))
    client = TestClient(app)
    principal, = client.get('/api/audio/collections').json()['colecciones']
    assert principal['nombre'] == 'Biblioteca musical' and principal['unificada']
    assert principal['tabla'] == 'audio_segmentos'
    assert api.tabla_audio(170002) == 'audio_segmentos'
    assert len(client.get('/api/audio/collections?incluir_auxiliares=true').json()['colecciones']) == 2


def test_motor_invalida_snapshots_despues_de_escribir_y_revertir(tmp_path):
    from backend.engine_adapter import EngineAdapter
    engine = EngineAdapter(str(tmp_path))
    try:
        revision = engine.data_revision
        insert = engine.execute_query("INSERT INTO estudiantes VALUES (2147483000, 'Prueba', 'BD2', 15.0);")
        assert insert['status'] == 'success', insert
        assert engine.data_revision > revision
        sesion = 'cache_audio'
        assert engine.execute_query('BEGIN TRANSACTION;', sesion)['status'] == 'success'
        assert engine.execute_query('UPDATE estudiantes SET promedio = 18.0 WHERE id = 2147483000;', sesion)['status'] == 'success'
        revision = engine.data_revision
        assert engine.execute_query('ROLLBACK;', sesion)['status'] == 'success'
        assert engine.data_revision > revision
        fila = engine.execute_query('SELECT promedio FROM estudiantes WHERE id = 2147483000;')
        assert fila['status'] == 'success' and fila['rows'] == [[15.0]]
    finally:
        engine.pool.close_all()
