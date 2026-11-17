import copy

import numpy as np
import pytest

from deteccion import acapella, letras

CATALOGO = {
    'a1': {'track_id': 'a1', 'titulo': 'Canción A', 'artista': 'Artista A', 'genero': 'pop', 'ruta': 'bench/data/a1.wav'},
    'b2': {'track_id': 'b2', 'titulo': 'Canción B', 'artista': 'Artista B', 'genero': 'rock', 'ruta': 'bench/data/b2.wav'},
}

FILAS = [
    ('a1', 30.0, 34.0, 'tu mirada tierna la que me entregaba'),
    ('a1', 34.0, 38.0, 'la tibia esa dulce de la madrugada'),
    ('a1', 38.0, 44.0, 'no estaba seguro si era un sueño o no'),
    ('b2', 10.0, 14.0, 'corazón de piedra camino sin rumbo'),
    ('b2', 14.0, 18.0, 'la noche me encuentra bailando contigo'),
]


class MotorFalso:
    def __init__(self, existe=True):
        self.existe = existe
        self.consultas = []

    def execute_query(self, sql):
        self.consultas.append(sql)
        if not self.existe:
            return {'status': 'error', 'error': 'tabla inexistente'}
        if 'MATCH' not in sql:
            return {'status': 'success', 'columns': ['id'], 'rows': []}
        consulta = set(sql.split("MATCH(texto, '")[1].split("'")[0].split())
        puntuadas = [(t, i, f, float(len(consulta & set(x.split())))) for t, i, f, x in FILAS]
        filas = sorted((p for p in puntuadas if p[3] > 0), key=lambda p: -p[3])[:5]
        return {'status': 'success', 'columns': ['track_id', 'inicio_s', 'fin_s', 's'], 'rows': [list(f) for f in filas]}


@pytest.fixture(autouse=True)
def catalogo(monkeypatch, tmp_path):
    monkeypatch.setattr(acapella, 'cargar_catalogo', lambda validar=True: CATALOGO)
    monkeypatch.setattr(acapella, 'directorio_modelo', lambda: tmp_path)


def audio(segundos=20, sr=16000):
    return (0.1 * np.sin(np.arange(int(segundos * sr)) * 0.05)).astype(np.float32)


def con_frases(monkeypatch, frases):
    monkeypatch.setattr(letras, 'transcribir', lambda y, sr: frases)


def test_esquema_igual_al_de_detect(monkeypatch):
    con_frases(monkeypatch, [(0.0, 4.0, 'tu mirada tierna la que me entregaba'), (4.0, 8.0, 'la tibia esa dulce de la madrugada'),
                             (8.0, 14.0, 'no estaba seguro si era un sueño o no')])
    r = letras.detectar(audio(14), 16000, MotorFalso())
    assert r['posible_coincidencia'] and r['conclusion'] == 'Posible uso no autorizado de «Canción A» de Artista A'
    c, = r['coincidencias']
    assert {'track_id', 'titulo', 'artista', 'inicio_s', 'fin_s', 'original_inicio_s', 'original_fin_s',
            'porcentaje_similitud', 'votos', 'metodo_verificacion'} <= set(c)
    assert c['track_id'] == 'a1' and c['metodo_verificacion'] == 'Letra cantada (Whisper + BM25)'
    assert abs(c['original_inicio_s'] - 30) <= 10 and c['fin_s'] - c['inicio_s'] >= 5
    assert 0 <= c['porcentaje_similitud'] <= 100
    assert r['segmentos'] == [] and 'tiempo_ms' in r['metricas'] and r['texto_reconocido']


def test_consulta_usa_match_bm25_con_la_frase_escapada(monkeypatch):
    motor = MotorFalso()
    con_frases(monkeypatch, [(0.0, 5.0, "tu mirada tierna' DROP TABLE x; la que me entregaba")])
    letras.detectar(audio(), 16000, motor)
    sql = motor.consultas[0]
    assert 'MATCH(texto,' in sql and 'USING BM25' in sql and 'LIMIT 5' in sql and ';' not in sql.split('FROM')[1]
    assert "'" not in sql.split("MATCH(texto, '")[1].split("'")[0]


def test_grabacion_sin_letra(monkeypatch):
    con_frases(monkeypatch, [])
    r = letras.detectar(audio(), 16000, MotorFalso())
    assert not r['coincidencias'] and not r['posible_coincidencia']
    assert r['conclusion'] == 'No se reconoció letra; canta la canción con su letra'
    assert r['texto_reconocido'] == ''


def test_silencio_no_se_transcribe(monkeypatch):
    llamadas = []
    monkeypatch.setattr(letras, 'transcribir', lambda y, sr: llamadas.append(1) or [(0, 1, 'invento')])
    r = letras.detectar(np.zeros(16000 * 8, dtype=np.float32), 16000, MotorFalso())
    assert not llamadas and not r['coincidencias']


def test_una_frase_corta_no_basta_y_una_larga_exacta_si(monkeypatch):
    con_frases(monkeypatch, [(0.0, 3.0, 'tu mirada tierna')])
    assert not letras.detectar(audio(6), 16000, MotorFalso())['coincidencias']
    con_frases(monkeypatch, [(0.0, 4.0, 'tu mirada tierna la que me entregaba')])
    r = letras.detectar(audio(6), 16000, MotorFalso())
    assert r['coincidencias'][0]['fin_s'] - r['coincidencias'][0]['inicio_s'] >= 5 - 1e-6 or r['duracion_s'] < 5


def test_dos_canciones_empatadas_no_se_reportan(monkeypatch):
    con_frases(monkeypatch, [(0.0, 4.0, 'tu mirada tierna la que me entregaba'), (4.0, 8.0, 'corazón de piedra camino sin rumbo')])
    assert not letras.detectar(audio(8), 16000, MotorFalso())['coincidencias']


def test_tabla_inexistente(monkeypatch):
    assert letras.tabla_lista(MotorFalso(existe=False)) is False
    assert letras.tabla_lista(MotorFalso()) is True
    base = {'duracion_s': 12, 'segmentos': [], 'coincidencias': [], 'posible_coincidencia': False,
            'conclusion': 'No se detectaron coincidencias con los parametros actuales.', 'metricas': {'tiempo_ms': 1}}
    monkeypatch.setattr(letras, 'transcribir', lambda *a: pytest.fail('no debe transcribir sin tabla'))
    monkeypatch.setattr(letras, 'desde_melodia', lambda *a: None)
    r = letras.complementar(copy.deepcopy(base), audio(12), 16000, MotorFalso(existe=False))
    assert r['coincidencias'] == [] and r['conclusion'] == base['conclusion']
    assert 'letra_error' in r['metricas']


def test_grabacion_corta_no_usa_la_melodia(monkeypatch):
    con_frases(monkeypatch, [])
    llamadas = []
    monkeypatch.setattr(acapella, 'reconocer', lambda *a, **k: llamadas.append(1))
    assert letras.desde_melodia(audio(6), 16000, 6.0) is None and not llamadas
    base = {'duracion_s': 6, 'segmentos': [], 'coincidencias': [], 'posible_coincidencia': False, 'conclusion': 'x', 'metricas': {}}
    r = letras.complementar(base, audio(6), 16000, MotorFalso())
    assert r['coincidencias'] == [] and not llamadas


def timbre(pct=90, ini=0, fin=12):
    return {'duracion_s': 20, 'segmentos': [{'inicio_s': 0, 'fin_s': 10, 'coincidencias': [], 'candidatos': []}],
            'coincidencias': [{'track_id': 'a1', 'titulo': 'Canción A', 'artista': 'Artista A', 'inicio_s': ini, 'fin_s': fin,
                               'original_inicio_s': 30, 'original_fin_s': 42, 'porcentaje_similitud': pct, 'votos': 4}],
            'posible_coincidencia': True, 'conclusion': 'Se detectaron posibles coincidencias de audio.', 'metricas': {'tiempo_ms': 5}}


def cantada(pct, ini=2, fin=12, track='a1'):
    return {'coincidencias': [{'track_id': track, 'titulo': CATALOGO[track]['titulo'], 'artista': CATALOGO[track]['artista'],
                               'inicio_s': ini, 'fin_s': fin, 'original_inicio_s': 30, 'original_fin_s': 40,
                               'porcentaje_similitud': pct, 'votos': 2, 'metodo_verificacion': letras.METODO}],
            'texto_reconocido': 'hola', 'frases': [], 'metricas': {'tiempo_ms': 99}}


def test_fusion_conserva_el_resultado_de_grabaciones():
    original = timbre()
    r = letras.fusionar(copy.deepcopy(original), None, None)
    esperado = [dict(c, tipo='grabacion') for c in original['coincidencias']]
    assert r['coincidencias'] == esperado
    assert r['segmentos'][0]['inicio_s'] == 0 and r['duracion_s'] == original['duracion_s']
    assert r['metricas']['tiempo_ms'] == 5


def test_fusion_sin_duplicados_gana_el_mayor_porcentaje():
    r = letras.fusionar(timbre(pct=80), cantada(95), None)
    assert len(r['coincidencias']) == 1 and r['coincidencias'][0]['tipo'] == 'cancion_cantada'
    r = letras.fusionar(timbre(pct=97), cantada(60), None)
    assert len(r['coincidencias']) == 1 and r['coincidencias'][0]['tipo'] == 'grabacion'
    assert 'Posible uso no autorizado detectado' in r['conclusion']


def test_fusion_tramos_distintos_se_conservan_y_la_conclusion_refleja_cualquier_ruta():
    r = letras.fusionar(timbre(ini=0, fin=5), cantada(70, ini=10, fin=20), None)
    assert [c['tipo'] for c in r['coincidencias']] == ['grabacion', 'cancion_cantada']
    vacio = {'duracion_s': 20, 'segmentos': [], 'coincidencias': [], 'posible_coincidencia': False,
             'conclusion': 'No se detectaron coincidencias con los parametros actuales.', 'metricas': {}}
    r = letras.fusionar(vacio, cantada(88), None)
    assert r['posible_coincidencia'] and r['conclusion'].startswith('Posible uso no autorizado detectado')
    assert r['texto_reconocido'] == 'hola'


def test_melodia_solo_si_la_letra_no_encontro_nada(monkeypatch):
    con_frases(monkeypatch, [])
    melodia = cantada(71, ini=0, fin=20, track='b2')
    melodia['coincidencias'][0]['metodo_verificacion'] = 'Melodía (DTW)'
    monkeypatch.setattr(letras, 'desde_melodia', lambda y, sr, d: melodia)
    base = {'duracion_s': 20, 'segmentos': [], 'coincidencias': [], 'posible_coincidencia': False, 'conclusion': 'x', 'metricas': {}}
    r = letras.complementar(base, audio(20), 16000, MotorFalso())
    assert r['coincidencias'][0]['metodo_verificacion'] == 'Melodía (DTW)'
    monkeypatch.setattr(letras, 'desde_melodia', lambda *a: pytest.fail('no debía usarse la melodía'))
    con_frases(monkeypatch, [(0.0, 4.0, 'tu mirada tierna la que me entregaba'), (4.0, 8.0, 'la tibia esa dulce de la madrugada')])
    base = {'duracion_s': 20, 'segmentos': [], 'coincidencias': [], 'posible_coincidencia': False, 'conclusion': 'x', 'metricas': {}}
    assert letras.complementar(base, audio(20), 16000, MotorFalso())['coincidencias'][0]['tipo'] == 'cancion_cantada'


class MotorSinIndice(MotorFalso):

    def execute_query(self, sql):
        if 'MATCH' in sql:
            return {'status': 'error', 'error': "Error [SEMANTICO]: la columna 'texto' de 'letras_acapella' no tiene indice invertido"}
        return super().execute_query(sql)


def test_tabla_sin_indice_se_detecta_y_el_mensaje_es_claro(monkeypatch):
    assert letras.estado_tabla(MotorSinIndice()) == 'sin_indice'
    assert not letras.tabla_lista(MotorSinIndice())
    base = {'duracion_s': 12, 'segmentos': [], 'coincidencias': [], 'posible_coincidencia': False, 'conclusion': 'x', 'metricas': {}}
    monkeypatch.setattr(letras, 'desde_melodia', lambda *a: None)
    r = letras.complementar(base, audio(12), 16000, MotorSinIndice())
    assert r['metricas']['letra_error'] == letras.MENSAJE_ACTUALIZANDO and 'SEMANTICO' not in r['metricas']['letra_error']


class MotorRegistrador(MotorFalso):
    def __init__(self, interrumpir_en=None):
        super().__init__()
        self.sql = []
        self.interrumpir_en = interrumpir_en

    def execute_query(self, sql):
        self.sql.append(sql)
        if self.interrumpir_en and self.interrumpir_en in sql:
            raise ConnectionError('el motor se reinició')
        return {'status': 'success', 'columns': [], 'rows': []}


def test_reconstruir_usa_la_tabla_inactiva_y_cambia_al_final(tmp_path):
    assert letras.tabla_activa() == letras.TABLA
    motor = MotorRegistrador()
    letras.cargar_en_motor(motor, [('a1', 1.0, 2.0, 'hola mundo bonito')])
    assert any('CREATE TABLE letras_acapella_b' in q for q in motor.sql)
    assert not any('DROP TABLE letras_acapella ' in q or 'CREATE TABLE letras_acapella (' in q for q in motor.sql)
    assert letras.tabla_activa() == 'letras_acapella_b'
    letras.cargar_en_motor(MotorRegistrador(), [('a1', 1.0, 2.0, 'hola mundo bonito')])
    assert letras.tabla_activa() == letras.TABLA


def test_carga_interrumpida_deja_intacta_la_tabla_activa(tmp_path):
    motor = MotorRegistrador(interrumpir_en='INSERT INTO')
    with pytest.raises(ConnectionError):
        letras.cargar_en_motor(motor, [('a1', 1.0, 2.0, 'hola mundo bonito')])
    assert letras.tabla_activa() == letras.TABLA
