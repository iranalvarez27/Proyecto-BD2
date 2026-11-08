from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from deteccion.detector import BusquedaAudio, Detector, Parametros, alinear, fusionar
from index.vector.exacto import knn_exacto_lote


def test_busqueda_hibrida_plana_conserva_top_k_exacto_de_ambas_representaciones():
    rng = np.random.default_rng(42)
    x = rng.random((201, 13), dtype=np.float32)
    q = rng.random((9, 13), dtype=np.float32)
    k = 17
    ids = [('pista', i) for i in range(len(x))]
    busqueda = BusquedaAudio(x, ids, 'EXACTO', 'hibrida')
    posiciones, distancias = busqueda.buscar(q, k)

    for columna, transformar in ((0, lambda a: a), (k, np.sqrt)):
        esperado, dist = knn_exacto_lote(transformar(q), transformar(x), k, 'cosine')
        np.testing.assert_array_equal(posiciones[:, columna:columna + k], esperado)
        np.testing.assert_allclose(distancias[:, columna:columna + k], dist, atol=1e-6)


def hit(t, original, pista='A', score=.94):
    return dict(consulta_s=t, original_s=original, track_id=pista, similitud=score)


def test_alineacion_recupera_desfase_y_velocidad_sin_duplicar_votos():
    params = Parametros()
    hits = [hit(t, 12 + 1.05*t) for t in np.arange(0, 4, .5)]
    hits += [hit(0, 12, score=.98)] * 8
    resultado = alinear(hits, params)
    assert resultado[0]['track_id'] == 'A'
    assert resultado[0]['votos'] == 8
    assert alinear([hit(0, 12)] * 10, params) == []


def test_vecinos_sin_coherencia_y_baja_similitud_se_descartan():
    params = Parametros(tolerancia_s=.2)
    assert not alinear([hit(0, 0), hit(1, 10), hit(2, 20)], params)
    assert not alinear([hit(t, 10+t, score=.2) for t in range(4)], params)


def test_fusion_conserva_dos_originales_y_separa_saltos():
    params = Parametros()
    a = alinear([hit(t, t + 4) for t in range(4)], params)[0]
    b = {**a, 'track_id': 'B'}
    c = {**a, 'evidencia_inicio_s': 5, 'evidencia_fin_s': 8}
    salto = {**a, 'desplazamiento_s': 30, 'evidencia_inicio_s': 10, 'evidencia_fin_s': 13}
    eventos = fusionar([
        dict(inicio_s=0, fin_s=5, coincidencias=[a, b]),
        dict(inicio_s=5, fin_s=10, coincidencias=[c]),
        dict(inicio_s=10, fin_s=15, coincidencias=[salto]),
    ], 2, 15, params)
    assert len(eventos) == 3
    assert eventos[0]['inicio_s'] == 0 and eventos[0]['fin_s'] == 10


@pytest.mark.parametrize('cambio', [dict(segmento_s=2), dict(paso_s=0), dict(umbral=float('nan')),
                                    dict(k=0), dict(min_votos=1), dict(metodo='otro')])
def test_validacion_parametros(cambio):
    with pytest.raises(ValueError):
        replace(Parametros(), **cambio).validar()


def extractor_falso():
    def ventanas(y, paso):
        tiempos = np.arange(0, len(y)/10 - 2 + .001, paso)
        return tiempos, np.tile([1., 0.], (len(tiempos), 1))
    return SimpleNamespace(meta={'sr': 10, 'seg_s': 2}, vectores_senal=ventanas)


def test_deteccion_con_cola_y_silencio():
    detector = Detector(np.array([[1., 0.]] * 5), [('A', i) for i in range(5)], extractor_falso())
    res = detector.detectar(np.ones(113))
    assert res['posible_coincidencia']
    assert res['segmentos'][-1]['fin_s'] == 11.3
    assert all(5 <= s['fin_s'] - s['inicio_s'] <= 10 for s in res['segmentos'])
    assert not detector.detectar(np.zeros(113))['posible_coincidencia']
    with pytest.raises(ValueError):
        detector.detectar(np.ones(49))
    with pytest.raises(ValueError):
        detector.detectar(np.array([float('nan')] * 60))


def test_extractor_cubre_ultima_ventana_y_valida_salto():
    from multimedia.bovw import Extractor
    ext = Extractor.__new__(Extractor)
    ext.tipo, ext.meta = 'audio', {'sr': 10, 'seg_s': 2}
    ext.idf, ext.codebook = np.ones(2), np.array([[1., 0.], [0., 1.]])
    ext._descriptores_lote = lambda ventanas: np.tile([[1., 0.]], (len(ventanas), 1, 1))
    tiempos, q = ext.vectores_senal(np.ones(63), .5)
    assert tiempos[-1] == 4.3
    assert len(q) == len(tiempos)
    with pytest.raises(ValueError):
        ext.vectores_senal(np.ones(63), 0)


def test_mfcc_por_lote_equivale_a_ventana_por_ventana():
    from multimedia import mfcc
    ventanas = np.random.default_rng(3).normal(size=(5, 4410)).astype(np.float32)
    lote = mfcc.extraer_mfcc_lote(ventanas, sr=22050, n_fft=2048, hop=512, n_mfcc=20)
    for i, ventana in enumerate(ventanas):
        np.testing.assert_allclose(lote[i], mfcc.extraer_mfcc(ventana, 22050, 2048, 512, 20), atol=1e-4)
    assert mfcc.extraer_mfcc_lote(np.empty((3, 0))).shape == (3, 0, 19)


def test_vectores_por_lote_equivalen_a_tfidf_por_ventana():
    from multimedia import codebook
    from multimedia.bovw import Extractor, tfidf_denso
    rng = np.random.default_rng(8)
    ext = Extractor.__new__(Extractor)
    ext.tipo, ext.meta = 'audio', {'sr': 10, 'seg_s': 2}
    ext.codebook, ext.idf = rng.normal(size=(6, 3)).astype(np.float32), rng.random(6).astype(np.float32)
    descriptores = rng.normal(size=(4, 9, 3)).astype(np.float32)
    ext._descriptores_lote = lambda ventanas: descriptores
    lote = ext._vectores_lote(np.zeros((4, 20)))
    for i in range(4):
        np.testing.assert_array_equal(lote[i], tfidf_denso(codebook.histograma(descriptores[i], ext.codebook), ext.idf))


def test_poda_chroma_no_cambia_las_decisiones():
    from deteccion.chroma import UMBRAL, alinear_chroma
    rng = np.random.default_rng(5)
    for caso in range(30):
        notas = np.cumsum(rng.integers(1, 12, 150)) % 12
        ref = np.eye(12, dtype=np.float32)[notas] * .8 + rng.random((150, 12)).astype(np.float32) * .2
        ref /= np.linalg.norm(ref, axis=1, keepdims=True)
        if caso % 2:
            q = np.roll(ref[30:60], rng.integers(0, 12), axis=1) + rng.random((30, 12)).astype(np.float32) * rng.uniform(0, .6)
        else:
            q = np.eye(12, dtype=np.float32)[rng.integers(0, 12, 30)] + rng.random((30, 12)).astype(np.float32) * .3
        q = (q / np.linalg.norm(q, axis=1, keepdims=True)).astype(np.float32)
        completa, podada = alinear_chroma(q, ref), alinear_chroma(q, ref, UMBRAL)
        aceptada = completa is not None and completa['similitud'] >= UMBRAL
        assert aceptada == (podada is not None and podada['similitud'] >= UMBRAL)
        if aceptada:
            assert podada['similitud'] == completa['similitud']
            assert podada['transposicion_semitonos'] == completa['transposicion_semitonos']


def test_verificacion_secuencia_rechaza_timbres_sin_orden():
    rng = np.random.default_rng(10)
    q = rng.normal(size=(80, 19))
    ext = SimpleNamespace(meta={'sr': 10, 'seg_s': 2, 'hop': 1})
    detector = Detector(np.ones((2, 3)), [('A', 0), ('B', 0)], ext,
                        resolver_original=lambda pid: pid)
    detector._originales['A'] = np.vstack((rng.normal(size=(20, 19)), q))
    detector._originales['B'] = rng.normal(size=(100, 19))
    candidato = dict(track_id='A', desplazamiento_s=2., similitud=.9)
    resultado = detector.verificar_secuencia(candidato, q, 0, 5)
    assert resultado and resultado['similitud_secuencia'] > .99
    assert abs(resultado['desplazamiento_s'] - 2) < .1
    assert detector.verificar_secuencia({**candidato, 'track_id': 'B'}, q, 0, 5) is None


def test_vista_reduccion_ruido_mejora_senal_sin_cambiar_largo():
    from multimedia.mfcc import reducir_ruido_estacionario
    sr = 8000
    t = np.arange(2 * sr) / sr
    original = (.3 * np.sin(2*np.pi*220*t) + .2 * np.sin(2*np.pi*440*t)).astype(np.float32)
    ruido = np.random.default_rng(7).normal(0, .05, len(t)).astype(np.float32)
    limpia = reducir_ruido_estacionario(original + ruido, n_fft=512, hop=128)
    assert limpia.shape == original.shape
    assert np.isfinite(limpia).all()
    assert np.mean((limpia - original)**2) < np.mean(ruido**2)


def test_mfcc_persistentes_se_reutilizan_y_se_invalidan(tmp_path, monkeypatch):
    import deteccion.detector as modulo
    class Modelo:
        directorio = tmp_path / 'modelo'
        meta = {'dim': 3, 'n_mfcc': 4, 'sr': 10, 'huella_codebook': 'modelo-prueba'}
    modelo = Modelo()
    modelo.directorio.mkdir()
    normalizacion = modelo.directorio / 'estandarizacion.npz'
    normalizacion.write_bytes(b'modelo original')
    audio = tmp_path / 'original.wav'
    audio.write_bytes(b'audio original')
    llamadas = []
    def extraer(*args):
        llamadas.append(args)
        return np.full((4, 3), len(llamadas), dtype=np.float32)
    def firma():
        s = audio.stat()
        return s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino
    monkeypatch.setattr(modulo, '_extraer_original', extraer)
    modulo._mfcc_original.cache_clear()
    try:
        primera = modulo._mfcc_original(str(audio), modelo, firma())
        modulo._mfcc_original.cache_clear()
        segunda = modulo._mfcc_original(str(audio), modelo, firma())
        np.testing.assert_array_equal(primera, segunda)
        assert len(llamadas) == 1
        audio.write_bytes(b'audio modificado con otra duracion')
        modulo._mfcc_original(str(audio), modelo, firma())
        assert len(llamadas) == 2
        modulo._mfcc_original.cache_clear()
        normalizacion.write_bytes(b'otro modelo de normalizacion')
        modulo._mfcc_original(str(audio), modelo, firma())
        assert len(llamadas) == 3
        modulo._mfcc_original.cache_clear()
        for ruta in (modelo.directorio / 'secuencias').glob('*.npy'):
            ruta.write_bytes(b'cache incompleta')
        modulo._mfcc_original(str(audio), modelo, firma())
        assert len(llamadas) == 4
    finally:
        modulo._mfcc_original.cache_clear()


def test_secuencia_fft_equivale_a_coseno_directo_y_actualiza_consulta():
    rng = np.random.default_rng(33)
    fuente = rng.normal(size=(180, 19))
    consulta = fuente[60:110].copy()
    ext = SimpleNamespace(meta={'sr': 10, 'seg_s': 2, 'hop': 1})
    detector = Detector(np.ones((1, 3)), [('A', 0)], ext,
                        Parametros(umbral_secuencia=0), resolver_original=lambda pid: pid)
    detector._originales['A'] = fuente
    for _ in range(2):
        mejor = None
        qc = consulta - consulta.mean(axis=0)
        for velocidad in detector.params.velocidades:
            posiciones = np.arange(0, len(fuente) - 1, velocidad)
            original = np.stack([np.interp(posiciones, np.arange(len(fuente)), columna)
                                 for columna in fuente.T], axis=1)
            for inicio in range(len(original) - len(consulta) + 1):
                x = original[inicio:inicio + len(consulta)]
                xc = x - x.mean(axis=0)
                absoluto = np.sum(x * consulta) / (np.linalg.norm(x) * np.linalg.norm(consulta))
                dinamico = np.sum(xc * qc) / (np.linalg.norm(xc) * np.linalg.norm(qc))
                score = .5 * max(0., absoluto) + .5 * max(0., dinamico)
                if mejor is None or score > mejor[0]:
                    mejor = (score, velocidad * inicio / 10, velocidad)
        res = detector.verificar_secuencia(dict(track_id='A', similitud=.9), consulta, 0, 5)
        assert res['similitud_secuencia'] == pytest.approx(mejor[0], abs=1e-12)
        assert res['desplazamiento_s'] == pytest.approx(mejor[1])
        assert res['velocidad'] == mejor[2]
        consulta[:] = rng.normal(size=consulta.shape)


@pytest.mark.parametrize('metodo', ['HNSW', 'IVF'])
def test_indices_aproximados_integran_el_detector(metodo):
    detector = Detector(np.array([[1., 0.]] * 5), [('A', i) for i in range(5)],
                        extractor_falso(), Parametros(metodo=metodo))
    resultado = detector.detectar(np.ones(100))
    assert resultado['posible_coincidencia']
    assert resultado['parametros']['metodo'] == metodo


@pytest.mark.parametrize('muestras, bloques', [(5000, 1), (5001, 1), (5100, 1), (10001, 2)])
def test_cola_menor_que_el_salto_no_duplica_bloque(muestras, bloques):
    sr = 1000
    def ventanas(y, paso):
        t = np.arange(0, len(y)/sr - 2 + .001, paso)
        return t, np.tile([1., 0.], (len(t), 1))
    ext = SimpleNamespace(meta={'sr': sr, 'seg_s': 2}, vectores_senal=ventanas)
    detector = Detector(np.array([[1., 0.]] * 5), [('A', i) for i in range(5)], ext)
    res = detector.detectar(np.ones(muestras))
    assert len(res['segmentos']) == bloques
    assert res['segmentos'][0]['inicio_s'] == 0
    assert res['segmentos'][-1]['fin_s'] == muestras/sr
    assert all(5 <= s['fin_s'] - s['inicio_s'] <= 10 for s in res['segmentos'])


def test_decodificacion_alternativa_usa_ffmpeg_y_devuelve_mono(monkeypatch):
    from multimedia import mfcc
    def fallar(*a, **kw):
        raise RuntimeError('cabecera mp3 no admitida')
    monkeypatch.setattr(mfcc.librosa, 'load', fallar)
    monkeypatch.setattr(mfcc.shutil, 'which', lambda nombre: 'ffmpeg')
    comandos = []
    def ejecutar(comando, **kw):
        comandos.append(comando)
        return SimpleNamespace(stdout=np.array([.1, -.1, .2], dtype='<f4').tobytes())
    monkeypatch.setattr(mfcc.subprocess, 'run', ejecutar)
    y = mfcc.cargar_audio('original.mp3', sr=16000)
    np.testing.assert_allclose(y, [.1, -.1, .2])
    assert comandos[0][comandos[0].index('-ar') + 1] == '16000'
    assert comandos[0][comandos[0].index('-protocol_whitelist') + 1] == 'file,pipe'


def test_decodificacion_no_acepta_salida_vacia_del_fallback(monkeypatch):
    from multimedia import mfcc
    def fallar(*a, **kw):
        raise RuntimeError('audio invalido')
    monkeypatch.setattr(mfcc.librosa, 'load', fallar)
    monkeypatch.setattr(mfcc.shutil, 'which', lambda nombre: 'ffmpeg')
    monkeypatch.setattr(mfcc.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=b''))
    with pytest.raises(ValueError, match='recuperable'):
        mfcc.cargar_audio('vacio.mp3')


def test_chroma_alinea_transposicion_y_cambio_de_tempo():
    from deteccion.chroma import alinear_chroma
    rng = np.random.default_rng(17)
    notas = np.cumsum(rng.integers(1, 12, 120)) % 12
    referencia = np.eye(12, dtype=np.float32)[notas]
    consulta = np.roll(referencia[25:65], 3, axis=1)
    consulta = np.repeat(consulta, [2 if i % 4 == 0 else 1 for i in range(len(consulta))], axis=0)
    res = alinear_chroma(consulta, referencia)
    assert res and res['similitud'] > .99
    assert res['transposicion_semitonos'] == 3
    assert res['camino'][0, 1] == 25
    assert res['camino'][-1, 1] == 64


def test_chroma_rechaza_acorde_constante_y_secuencia_ajena():
    from deteccion.chroma import alinear_chroma
    constante = np.tile(np.eye(12)[0], (40, 1))
    assert alinear_chroma(constante, constante) is None
    rng = np.random.default_rng(19)
    consulta = np.eye(12)[rng.integers(0, 12, 40)]
    referencia = np.eye(12)[rng.integers(0, 12, 120)]
    res = alinear_chroma(consulta, referencia)
    assert res is None or res['similitud'] < .85


def test_detector_incluye_chroma_en_resultados_y_bloques(monkeypatch, tmp_path):
    from deteccion import chroma
    ext = extractor_falso()
    ext.meta['hop'] = 1
    ext._descriptores_audio = lambda y: np.ones((len(y), 2))
    detector = Detector(np.array([[1., 0.]] * 5), [('A', i) for i in range(5)], ext,
                        resolver_original=lambda p: tmp_path / p)
    monkeypatch.setattr(detector, '_precargar_originales', lambda candidatos: None)
    monkeypatch.setattr(detector, 'verificar_secuencia', lambda *args: None)
    evento = dict(track_id='A', inicio_s=0., fin_s=14., evidencia_inicio_s=0., evidencia_fin_s=14.,
                  original_inicio_s=20., original_fin_s=34., similitud=.9,
                  porcentaje_similitud=90., votos=20, metodo_verificacion='Chroma CQT + DTW')
    llamadas = []
    def verificar(y, sr, hits, params, resolver, carpeta, existentes):
        llamadas.append((sr, len(hits), existentes))
        return [evento]
    monkeypatch.setattr(chroma, 'verificar_tonal', verificar)
    res = detector.detectar(np.ones(150))
    assert llamadas and llamadas[0][0] == 10 and llamadas[0][1] > 0
    assert res['coincidencias'] == [evento]
    assert res['posible_coincidencia']
    assert all(evento in s['coincidencias'] for s in res['segmentos'])
    assert 'modo' not in res['parametros']


def test_chroma_complementa_sin_solapar_coincidencias(tmp_path, monkeypatch):
    from deteccion import chroma
    ruta = tmp_path / 'original.wav'
    ruta.write_bytes(b'original')
    monkeypatch.setattr(chroma, 'extraer_chroma', lambda y: np.eye(12)[np.arange(30) % 12])
    monkeypatch.setattr(chroma, 'chroma_original', lambda *args: np.eye(12)[np.arange(100) % 12])
    def alinear(q, r, minimo=0.):
        return dict(similitud=.95, camino=np.column_stack((np.arange(len(q)), np.arange(len(q)) + 20)))
    monkeypatch.setattr(chroma, 'alinear_chroma', alinear)
    existente = dict(track_id='A', inicio_s=5., fin_s=9.)
    nuevos = chroma.verificar_tonal(np.ones(15 * chroma.SR), chroma.SR,
        [hit(t, t) for t in range(12)], Parametros(), lambda p: ruta, tmp_path, [existente])
    assert nuevos
    assert all(e['fin_s'] <= 5 or e['inicio_s'] >= 9 for e in nuevos)
    assert all(e['original_fin_s'] > e['original_inicio_s'] for e in nuevos)
    for a, b in zip(sorted(nuevos, key=lambda e: e['inicio_s']), sorted(nuevos, key=lambda e: e['inicio_s'])[1:]):
        assert a['fin_s'] <= b['inicio_s']


def test_verificacion_por_pista_conserva_resultados_y_orden():
    from copy import deepcopy
    rng = np.random.default_rng(71)
    ext = SimpleNamespace(meta={'sr': 10, 'seg_s': 2, 'hop': 1})
    pistas = [str(i) for i in range(6)]
    fuentes = {p: rng.normal(size=(180, 19)) for p in pistas}
    consultas = [rng.normal(size=(150, 19)) for _ in range(2)]
    segmentos = [dict(inicio_s=t, fin_s=t + 5,
                      coincidencias=[dict(track_id=p, similitud=.9) for p in pistas[turno:] + pistas[:turno]])
                 for turno, t in enumerate((0, 5, 10))]
    def detector():
        d = Detector(np.ones((6, 3)), [(p, 0) for p in pistas], ext,
                     Parametros(umbral_secuencia=0), resolver_original=lambda pid: pid)
        d._originales.update(fuentes)
        return d
    anterior = detector()
    esperado = deepcopy(segmentos)
    for segmento in esperado:
        resultados = []
        for candidato in segmento['coincidencias']:
            opciones = [anterior.verificar_secuencia(candidato, desc, segmento['inicio_s'], segmento['fin_s'])
                        for desc in consultas]
            resultados.append(max(opciones, key=lambda c: c['similitud']))
        segmento['coincidencias'] = sorted(resultados, key=lambda c: -c['similitud'])
    actual = deepcopy(segmentos)
    detector()._verificar_segmentos(actual, consultas)
    assert actual == esperado
