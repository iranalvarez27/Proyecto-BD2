import json

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
import librosa
import numpy as np
import pytest
import soundfile as sf

from deteccion import acapella as a

MELODIAS = {
    'cancion_a': [0, 2, 4, 5, 7, 5, 4, 2, 0, 4, 7, 12, 7, 4, 2, 0],
    'cancion_b': [9, 7, 5, 4, 2, 4, 5, 7, 9, 11, 9, 7, 5, 4, 2, 0],
    'cancion_c': [0, 0, 7, 7, 9, 9, 7, 5, 5, 4, 4, 2, 2, 0, 3, 1],
}


def cantar(notas, transponer=0, tempo=1.0, nota_s=0.5, repetir=2):
    sr = a.SR
    partes = []
    for nota in list(notas) * repetir:
        f = librosa.midi_to_hz(60 + nota + transponer)
        largo = int(nota_s * tempo * sr)
        t = np.arange(largo) / sr
        tono = sum((0.6 ** k) * np.sin(2 * np.pi * f * (k + 1) * t) for k in range(5))
        envolvente = np.minimum(1, np.minimum(t, t[::-1]) * 40)
        partes.append(tono * envolvente)
    y = np.concatenate(partes)
    return (0.8 * y / np.abs(y).max()).astype(np.float32)


@pytest.fixture
def repertorio(tmp_path, monkeypatch):
    monkeypatch.setattr(a, 'directorio_modelo', lambda: tmp_path)
    a.limpiar_cache()
    rng = np.random.default_rng(0)
    catalogo = {}
    for tid, notas in MELODIAS.items():
        voz = cantar(notas, repetir=3)
        bajo = cantar([n - 24 for n in notas], repetir=3) * 0.4
        mezcla = voz + bajo[:len(voz)] + 0.02 * rng.standard_normal(len(voz)).astype(np.float32)
        np.save(tmp_path / f'{tid}.npy', a.melodia(mezcla).astype(np.float16))
        catalogo[tid] = {'track_id': tid, 'titulo': tid.replace('_', ' ').title(), 'artista': 'Prueba',
                         'ruta': f'bench/data/musica_propia/{tid}.wav', 'duracion_s': len(voz) / a.SR}
    (tmp_path / 'catalogo.json').write_text(json.dumps(catalogo), encoding='utf-8')
    yield tmp_path
    a.limpiar_cache()


def test_clase_suave_es_circular():
    v = a._clase_suave(np.array([[11.6]]), np.array([[1.0]]))[0]
    assert v.argmax() in (0, 11) and v[0] > v[6]


def test_dtw_compilado_igual_a_librosa():
    if a._dtw_final is None:
        pytest.skip('numba no disponible')
    rng = np.random.default_rng(1)
    q = rng.random((30, 12))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    q[::5] = 0
    r = rng.random((200, 12))
    r /= np.linalg.norm(r, axis=1, keepdims=True)
    activos = np.linalg.norm(q, axis=1) > 1e-6
    compilado = a._dtw_final(q, r, ~activos, a.PESO_SALTO)
    referencia = [librosa.sequence.dtw(C=a._costos(q, r, t), subseq=True, backtrack=False,
                                       step_sizes_sigma=a.PASOS, weights_add=a.PESOS_PASOS)[-1].min()
                  for t in range(12)]
    np.testing.assert_allclose(compilado, referencia, atol=1e-9)


def test_comparar_detecta_la_transposicion():
    rng = np.random.default_rng(2)
    r = rng.random((300, 12)).astype(np.float32)
    r /= np.linalg.norm(r, axis=1, keepdims=True)
    q = np.roll(r[100:160], -3, axis=1)
    res = a.comparar(q, r)
    assert res['transposicion_semitonos'] == -3
    assert res['similitud'] > 0.99
    assert 100 * a.PASO_S - 1 <= res['original_inicio_s'] <= 100 * a.PASO_S + 1


@pytest.mark.parametrize('transponer,tempo', [(0, 1.0), (3, 1.15), (-5, 0.9)])
def test_reconoce_la_cancion_cantada(repertorio, transponer, tempo):
    voz = cantar(MELODIAS['cancion_b'][3:15], transponer=transponer, tempo=tempo, repetir=1)
    res = a.reconocer(np.concatenate([voz, voz]))
    assert res['ranking'][0]['track_id'] == 'cancion_b'
    assert res['ranking'][0]['transposicion_semitonos'] == transponer
    assert res['metricas']['canciones_comparadas'] == 3


def test_casos_borde(repertorio):
    with pytest.raises(ValueError, match='al menos'):
        a.reconocer(cantar(MELODIAS['cancion_a'], repetir=1)[:a.SR * 3])
    with pytest.raises(ValueError, match='silencio'):
        a.reconocer(np.zeros(a.SR * 10, np.float32))
    with pytest.raises(ValueError, match='no debe superar'):
        a.reconocer(np.zeros(int(a.SR * (a.DURACION_MAX_S + 1)), np.float32) + 0.1)
    res = a.reconocer(cantar(MELODIAS['cancion_a'], repetir=1), excluir=tuple(MELODIAS))
    assert res['ranking'] == [] and not res['posible_coincidencia']


def test_sin_repertorio(tmp_path, monkeypatch):
    monkeypatch.setattr(a, 'directorio_modelo', lambda: tmp_path)
    a.limpiar_cache()
    with pytest.raises(FileNotFoundError):
        a.reconocer(cantar(MELODIAS['cancion_a'], repetir=1))
    a.limpiar_cache()


def test_api(repertorio, tmp_path):
    from backend.audio_detection import agregar_acapella
    raiz = tmp_path / 'app'
    (raiz / 'data' / 'uploads').mkdir(parents=True)
    sf.write(raiz / 'data' / 'uploads' / 'toma.wav', cantar(MELODIAS['cancion_c'], repetir=1), a.SR)
    sf.write(raiz / 'data' / 'uploads' / 'corta.wav', np.zeros(a.SR, np.float32), a.SR)
    router = APIRouter(prefix='/api/audio')
    agregar_acapella(router, raiz, raiz)
    app = FastAPI()
    app.include_router(router)
    cliente = TestClient(app)

    canciones = cliente.get('/api/audio/acapella/songs').json()['canciones']
    assert {c['track_id'] for c in canciones} == set(MELODIAS)
    assert all(c['audio_url'].startswith('/api/media/bench/data/') for c in canciones)

    res = cliente.post('/api/audio/acapella/detect', json={'path': 'uploads/toma.wav'})
    assert res.status_code == 200
    datos = res.json()
    assert datos['modo'] == 'acapella' and datos['ranking'][0]['track_id'] == 'cancion_c'
    assert 'ruta' not in datos['ranking'][0] and datos['audio_url'] == '/api/media/uploads/toma.wav'

    assert cliente.post('/api/audio/acapella/detect', json={'path': 'uploads/corta.wav'}).status_code == 400
    assert cliente.post('/api/audio/acapella/detect', json={'path': '../fuera.wav'}).status_code == 400
    assert cliente.post('/api/audio/acapella/detect', json={'path': 'uploads/toma.wav', 'top': 0}).status_code == 422


def test_preparar_tolera_canciones_fallidas(tmp_path, monkeypatch):
    monkeypatch.setattr(a, 'directorio_modelo', lambda: tmp_path)
    a.limpiar_cache()

    def preparar_una(tid, carpeta):
        if tid == 'sin_audio':
            raise FileNotFoundError('no existe el audio')
        np.save(tmp_path / f'{tid}.npy', np.ones((20, 12), np.float16))
        return {'track_id': tid, 'titulo': tid, 'artista': 'X', 'ruta': '', 'duracion_s': 1, 'fotogramas': 20, 'tiempo_s': 0}

    monkeypatch.setattr(a, '_preparar_una', preparar_una)
    eventos = []
    catalogo = a.preparar(['uno', 'sin_audio', 'dos'], workers=0, progreso=lambda *e: eventos.append(e))
    assert set(catalogo) == {'uno', 'dos'}
    assert [e[0] for e in eventos] == ['uno', 'sin_audio', 'dos'] and eventos[1][2] == 'no existe el audio'
    assert set(a.cargar_catalogo()) == {'uno', 'dos'}

    assert a.iniciar_preparacion(['tres']) is True
    for _ in range(200):
        if not a.estado()['preparacion']['activa']:
            break
        import time
        time.sleep(0.02)
    estado = a.estado()
    assert estado['canciones'] == 3 and estado['preparacion']['hechas'] == 1 and not estado['preparacion']['error']
    a.limpiar_cache()


def test_api_estado_y_preparacion(repertorio, tmp_path, monkeypatch):
    from backend.audio_detection import agregar_acapella
    router = APIRouter(prefix='/api/audio')
    agregar_acapella(router, tmp_path, tmp_path)
    app = FastAPI()
    app.include_router(router)
    cliente = TestClient(app)

    estado = cliente.get('/api/audio/acapella/status').json()
    assert estado['canciones'] == 3 and estado['preparacion']['activa'] is False
    monkeypatch.setattr(a, 'CARPETA_AUDIO', tmp_path / 'no_existe')
    res = cliente.post('/api/audio/acapella/prepare', json={})
    assert res.status_code == 409 and 'audios originales' in res.json()['detail']
