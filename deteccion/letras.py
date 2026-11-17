import json
import os
from pathlib import Path
import re
import sys
import threading
import time

import numpy as np

from deteccion import acapella

MODELO = 'small'
SR_WHISPER = 16000
TABLA = 'letras_acapella'
METODO = 'Letra cantada (Whisper + BM25)'
PALABRAS_MIN = 3
PALABRAS_FRASE_UNICA = 6
TOLERANCIA_S = 10.0
TRAMO_MIN_S = 5.0
VENTAJA = 0.30
TOP_FILAS = 5
MAX_BYTES_TEXTO = 200
DURACION_MIN_S = 5.0
SILENCIO_RMS = 1e-3

_modelo = None
_modelo_lock = threading.Lock()
_preparacion_lock = threading.Lock()
_progresos = {}
_progreso_lock = threading.Lock()
ETAPAS = ('grabacion', 'letra', 'melodia')
_preparacion = {'activa': False, 'total': 0, 'hechas': 0, 'actual': None, 'omitidas': [], 'error': None}


def _cargar_modelo():
    global _modelo
    with _modelo_lock:
        if _modelo is None:
            from faster_whisper import WhisperModel
            _modelo = WhisperModel(MODELO, device='cpu', compute_type='int8')
        return _modelo


def transcribir(y, sr):
    y = np.asarray(y, dtype=np.float32)
    if y.ndim != 1 or not np.isfinite(y).all():
        raise ValueError('se requiere audio mono con muestras finitas')
    if sr != SR_WHISPER:
        import librosa
        y = librosa.resample(y, orig_sr=sr, target_sr=SR_WHISPER)
    modelo = _cargar_modelo()
    with _modelo_lock:
        frases = []
        for vad in (True, False):
            segmentos, _info = modelo.transcribe(y, language='es', vad_filter=vad, beam_size=3,
                                                 condition_on_previous_text=False)
            frases = [(float(s.start), float(s.end), s.text.strip()) for s in segmentos]
            if any(f[2] for f in frases):
                break
    return [f for f in frases if f[2]]


def _cargar_voz(ruta):
    import librosa
    y, _ = librosa.load(str(ruta), sr=SR_WHISPER, mono=True)
    return y


def _palabras(texto):
    return re.findall(r'[^\W_]+', texto.lower(), flags=re.UNICODE)


def _stop():
    from text.preprocesamiento import stopwords
    return set(stopwords('spanish'))


def palabras_utiles(texto):
    vacias = _stop()
    return [p for p in _palabras(texto) if len(p) >= 3 and p not in vacias]


def _consulta_segura(texto):
    return ' '.join(_palabras(texto))


def _sql(conexion, sql):
    res = conexion.execute_query(sql)
    if res.get('status') != 'success':
        raise ValueError(res.get('error') or 'error del motor')
    return res.get('columns') or [], res.get('rows') or []


def tabla_lista(conexion):
    try:
        _sql(conexion, f'SELECT id FROM {TABLA} WHERE id = 1')
        return True
    except (ValueError, ConnectionError, OSError):
        return False


def carpeta_letras():
    return acapella.directorio_modelo() / 'letras'


def _frases_cancion(tid, forzar=False):
    ruta = carpeta_letras() / f'{tid}.json'
    if ruta.is_file() and not forzar:
        return json.loads(ruta.read_text(encoding='utf-8'))
    voz = acapella.directorio_modelo() / 'voces' / f'{tid}.flac'
    if not voz.is_file():
        return None
    frases = transcribir(_cargar_voz(voz), SR_WHISPER)
    datos = {'track_id': tid, 'modelo': MODELO, 'frases': [list(f) for f in frases]}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix('.tmp')
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(temporal, ruta)
    return datos


def _literal(texto):
    return "'" + texto.replace("'", "''") + "'"


def _recortar(texto, max_bytes=MAX_BYTES_TEXTO):
    return texto.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')


def cargar_en_motor(conexion, filas):
    if tabla_lista(conexion):
        _sql(conexion, f'DROP TABLE {TABLA}')
    _sql(conexion, f'CREATE TABLE {TABLA} (id INT PRIMARY KEY, track_id VARCHAR(40), inicio_s FLOAT, '
                   f'fin_s FLOAT, texto VARCHAR({MAX_BYTES_TEXTO}))')
    for i, (tid, ini, fin, texto) in enumerate(filas, 1):
        _sql(conexion, f'INSERT INTO {TABLA} VALUES ({i}, {_literal(tid)}, {ini:.3f}, {fin:.3f}, '
                       f'{_literal(_recortar(texto))})')
    _sql(conexion, f'CREATE INDEX ON {TABLA} (texto) USING INVERTED')


def preparar(conexion, ids=None, forzar=False, progreso=None):
    catalogo = acapella.cargar_catalogo(validar=False)
    ids = [i for i in (ids or list(catalogo)) if i in catalogo]
    filas, omitidas = [], []
    for tid in ids:
        error = None
        try:
            datos = _frases_cancion(tid, forzar)
            if datos is None:
                error = 'aún no hay voz separada'
            else:
                for ini, fin, texto in datos['frases']:
                    if palabras_utiles(texto):
                        filas.append((tid, ini, fin, texto))
        except Exception as ex:
            error = str(ex)
        if error:
            omitidas.append({'track_id': tid, 'error': error})
        if progreso:
            progreso(tid, catalogo[tid], error)
    if not filas:
        raise ValueError('no hay letras que cargar: prepare primero las voces (python -m deteccion.acapella preparar)')
    cargar_en_motor(conexion, filas)
    return {'canciones': len({f[0] for f in filas}), 'frases': len(filas), 'omitidas': omitidas}


def estado():
    with _preparacion_lock:
        prep = {**_preparacion, 'omitidas': list(_preparacion['omitidas'])}
    carpeta = carpeta_letras()
    return {'canciones_con_letra': len(list(carpeta.glob('*.json'))) if carpeta.is_dir() else 0,
            'voces_disponibles': len(list((acapella.directorio_modelo() / 'voces').glob('*.flac'))),
            'modelo': MODELO, 'preparacion': prep}


def iniciar_preparacion(conexion, ids=None, forzar=False):
    with _preparacion_lock:
        if _preparacion['activa']:
            return False
        _preparacion.update(activa=True, total=len(ids or acapella.cargar_catalogo(validar=False)), hechas=0,
                            actual=None, omitidas=[], error=None)

    def avance(tid, info, error):
        with _preparacion_lock:
            _preparacion['hechas'] += 1
            _preparacion['actual'] = info['titulo']
            if error:
                _preparacion['omitidas'].append({'track_id': tid, 'error': error})

    def trabajo():
        try:
            preparar(conexion, ids, forzar, avance)
        except Exception as ex:
            with _preparacion_lock:
                _preparacion['error'] = str(ex)
        finally:
            with _preparacion_lock:
                _preparacion.update(activa=False, actual=None)

    threading.Thread(target=trabajo, name='letras-preparar', daemon=True).start()
    return True


def _buscar_frase(conexion, texto):
    consulta = _consulta_segura(texto)
    _cols, filas = _sql(conexion, f"SELECT track_id, inicio_s, fin_s, SCORE() AS s FROM {TABLA} "
                                  f"WHERE MATCH(texto, {_literal(consulta)}) USING BM25 ORDER BY s DESC LIMIT {TOP_FILAS}")
    return [(str(t), float(i), float(f), float(s)) for t, i, f, s in filas]


def _tramos(aciertos):
    tramos = []
    for a in sorted(aciertos, key=lambda x: x['q_ini']):
        desfase = a['o_ini'] - a['q_ini']
        if tramos and abs(desfase - tramos[-1]['desfase']) <= TOLERANCIA_S:
            tramos[-1]['aciertos'].append(a)
        else:
            tramos.append({'aciertos': [a], 'desfase': desfase})
    return tramos


def _evaluar(tramo):
    a = tramo['aciertos']
    return {'votos': sum(x['norma'] * x['peso'] for x in a), 'frases': len(a),
            'palabras_max': max(x['palabras'] for x in a),
            'norma_max': max(x['norma'] for x in a)}


def detectar(y, sr, conexion, duracion=None):
    inicio = time.perf_counter()
    duracion = duracion or len(y) / sr
    catalogo = acapella.cargar_catalogo(validar=False)
    frases = transcribir(y, sr) if float(np.sqrt(np.mean(np.square(y)))) >= SILENCIO_RMS else []
    texto = ' '.join(f[2] for f in frases)
    base = {'duracion_s': duracion, 'segmentos': [], 'coincidencias': [], 'posible_coincidencia': False,
            'texto_reconocido': texto, 'frases': [{'inicio_s': a, 'fin_s': b, 'texto': t} for a, b, t in frases]}

    def cerrar(conclusion, coincidencias=()):
        base.update(coincidencias=list(coincidencias), posible_coincidencia=bool(coincidencias),
                    conclusion=conclusion,
                    metricas={'tiempo_ms': round((time.perf_counter() - inicio) * 1000, 2),
                              'frases': len(frases)})
        return base

    if not frases or not palabras_utiles(texto):
        return cerrar('No se reconoció letra; canta la canción con su letra')

    por_cancion = {}
    maximos = []
    for q_ini, q_fin, frase in frases:
        palabras = palabras_utiles(frase)
        if len(palabras) < PALABRAS_MIN:
            continue
        filas = _buscar_frase(conexion, frase)
        if not filas:
            continue
        maximo = max(f[3] for f in filas) or 1.0
        maximos.append(maximo)
        mejor = {}
        for tid, o_ini, o_fin, score in filas:
            norma = score / maximo
            if tid not in mejor or norma > mejor[tid]['norma']:
                mejor[tid] = {'q_ini': q_ini, 'q_fin': q_fin, 'o_ini': o_ini, 'o_fin': o_fin,
                              'norma': norma, 'maximo': maximo, 'palabras': len(_palabras(frase))}
        for tid, a in mejor.items():
            por_cancion.setdefault(tid, []).append(a)

    referencia = max(maximos) if maximos else 1.0
    for aciertos in por_cancion.values():
        for a in aciertos:
            a['peso'] = a['maximo'] / referencia
    candidatas = []
    for tid, aciertos in por_cancion.items():
        evaluados = [(t, _evaluar(t)) for t in _tramos(aciertos)]
        tramo, ev = max(evaluados, key=lambda p: (p[1]['votos'], p[1]['frases']))
        candidatas.append((tid, tramo, ev))
    candidatas.sort(key=lambda c: -c[2]['votos'])
    if not candidatas:
        return cerrar('No se detectaron coincidencias')
    tid, tramo, ev = candidatas[0]
    segundo = candidatas[1][2]['votos'] if len(candidatas) > 1 else 0.0
    suficiente = ev['frases'] >= 2 or (ev['palabras_max'] >= PALABRAS_FRASE_UNICA and ev['norma_max'] >= 0.999)
    if not suficiente or ev['votos'] < (1 + VENTAJA) * segundo:
        return cerrar('No se detectaron coincidencias')

    a = tramo['aciertos']
    ini = min(x['q_ini'] for x in a)
    fin = max(x['q_fin'] for x in a)
    if fin - ini < TRAMO_MIN_S:
        fin = min(duracion, ini + TRAMO_MIN_S)
        ini = max(0.0, fin - TRAMO_MIN_S)
    o_ini = min(x['o_ini'] for x in a)
    o_fin = max(x['o_fin'] for x in a)
    meta = catalogo.get(tid, {})
    titulo, artista = meta.get('titulo') or 'Pista ' + tid, meta.get('artista') or 'Artista desconocido'
    c = {'track_id': tid, 'titulo': titulo, 'artista': artista, 'genero': meta.get('genero', ''),
         'inicio_s': round(ini, 2), 'fin_s': round(fin, 2),
         'original_inicio_s': round(o_ini, 2), 'original_fin_s': round(o_fin, 2),
         'porcentaje_similitud': round(100 * sum(x['norma'] for x in a) / len(a), 2),
         'votos': round(ev['votos'], 2), 'frases': ev['frases'], 'metodo_verificacion': METODO,
         'tipo': 'cancion_cantada'}
    return cerrar(f'Posible uso no autorizado de «{titulo}» de {artista}', [c])


def _solapan(a, b):
    return a['inicio_s'] < b['fin_s'] and b['inicio_s'] < a['fin_s']


def fusionar(timbre, letra, melodia=None):
    salida = timbre
    lista = [dict(c, tipo='grabacion') for c in timbre.get('coincidencias', [])]
    for c in timbre.get('segmentos', []):
        for x in c.get('coincidencias', []):
            x.setdefault('tipo', 'grabacion')
    nuevas = []
    for fuente in (letra, melodia):
        if fuente:
            nuevas += fuente.get('coincidencias', [])
    for n in nuevas:
        n.setdefault('tipo', 'cancion_cantada')
        repetida = next((e for e in lista if e['track_id'] == n['track_id'] and _solapan(e, n)), None)
        if repetida is None:
            lista.append(n)
        elif n['porcentaje_similitud'] > repetida['porcentaje_similitud']:
            lista[lista.index(repetida)] = n
    lista.sort(key=lambda e: (e['inicio_s'], e['track_id']))
    salida['coincidencias'] = lista
    salida['posible_coincidencia'] = bool(lista)
    if lista:
        titulos = []
        for e in lista:
            if e['titulo'] not in titulos:
                titulos.append(e['titulo'])
        salida['conclusion'] = 'Posible uso no autorizado detectado: ' + ', '.join(f'«{t}»' for t in titulos)
    if letra:
        salida['texto_reconocido'] = letra.get('texto_reconocido', '')
        salida['frases'] = letra.get('frases', [])
        salida.setdefault('metricas', {})['letra_ms'] = letra.get('metricas', {}).get('tiempo_ms')
    return salida


def desde_melodia(y, sr, duracion):
    if duracion < 10:
        return None
    try:
        r = acapella.reconocer(y, sr)
    except (ValueError, FileNotFoundError):
        return None
    mejor = (r.get('coincidencias') or [None])[0]
    if not mejor:
        return None
    similitud = mejor.get('porcentaje_similitud')
    if similitud is None:
        similitud = round(100 * float(mejor.get('similitud', 0)), 2)
    c = {'track_id': mejor['track_id'], 'titulo': mejor['titulo'], 'artista': mejor['artista'],
         'genero': mejor.get('genero', ''), 'inicio_s': 0.0, 'fin_s': round(duracion, 2),
         'original_inicio_s': round(float(mejor.get('original_inicio_s', 0.0)), 2),
         'original_fin_s': round(float(mejor.get('original_fin_s', 0.0)), 2),
         'porcentaje_similitud': float(similitud), 'votos': 1, 'metodo_verificacion': 'Melodía (DTW)',
         'tipo': 'cancion_cantada'}
    return {'coincidencias': [c]}


def iniciar_progreso(progreso_id):
    if not progreso_id:
        return
    with _progreso_lock:
        if len(_progresos) >= 50:
            _progresos.pop(next(iter(_progresos)))
        _progresos[progreso_id] = {e: 'espera' for e in ETAPAS}


def marcar(progreso_id, etapa, estado):
    if not progreso_id:
        return
    with _progreso_lock:
        if progreso_id in _progresos:
            _progresos[progreso_id][etapa] = estado


def leer_progreso(progreso_id):
    with _progreso_lock:
        return dict(_progresos.get(progreso_id, {}))


def complementar(resultado, y, sr, conexion, ruta_url=None, progreso_id=None):
    duracion = len(y) / sr
    letra = melodia = None
    try:
        marcar(progreso_id, 'letra', 'activo')
        if tabla_lista(conexion):
            letra = detectar(y, sr, conexion, duracion)
            if ruta_url:
                for c in letra['coincidencias']:
                    meta = acapella.cargar_catalogo(validar=False).get(c['track_id'], {})
                    c['audio_url'] = ruta_url(meta.get('ruta', ''))
        else:
            resultado.setdefault('metricas', {})['letra_error'] = 'Falta preparar las letras'
        marcar(progreso_id, 'letra', 'hecho')
        if not (letra and letra['coincidencias']):
            marcar(progreso_id, 'melodia', 'activo' if duracion >= 10 else 'omitida')
            melodia = desde_melodia(y, sr, duracion)
            marcar(progreso_id, 'melodia', 'hecho' if duracion >= 10 else 'omitida')
            if melodia and ruta_url:
                for c in melodia['coincidencias']:
                    meta = acapella.cargar_catalogo(validar=False).get(c['track_id'], {})
                    c['audio_url'] = ruta_url(meta.get('ruta', ''))
        else:
            marcar(progreso_id, 'melodia', 'omitida')
    except Exception as ex:
        resultado.setdefault('metricas', {})['letra_error'] = str(ex)
        for etapa in ('letra', 'melodia'):
            marcar(progreso_id, etapa, 'hecho')
    return fusionar(resultado, letra, melodia)


def _conexion_cli():
    import httpx
    url = os.environ.get('ENGINE_URL', 'http://127.0.0.1:8000').rstrip('/')
    try:
        httpx.get(url + '/api/tables', timeout=3).raise_for_status()

        class Http:
            def execute_query(self, sql, session_id=None):
                r = httpx.post(url + '/api/query', json={'query': sql, 'session_id': session_id}, timeout=600)
                r.raise_for_status()
                return r.json()
        print(f'Usando el motor en {url}')
        return Http()
    except Exception:
        from backend.engine_adapter import EngineAdapter
        print('El motor no responde: se abren los datos en proceso (no lo tengas encendido a la vez).')
        return EngineAdapter(str(acapella.RAIZ / 'data'))


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description='Letras de las canciones del repertorio (Whisper + índice invertido)')
    sub = p.add_subparsers(dest='orden', required=True)
    q = sub.add_parser('preparar', help='transcribe las voces y carga la tabla letras_acapella')
    q.add_argument('ids', nargs='*', help='track_id (por defecto, todas las voces disponibles)')
    q.add_argument('--forzar', action='store_true', help='volver a transcribir aunque exista la caché')
    sub.add_parser('estado')
    args = p.parse_args(argv)
    if args.orden == 'estado':
        print(json.dumps(estado(), ensure_ascii=False, indent=1))
        return
    inicio = time.time()

    def avance(tid, info, error):
        print(f'  {info["titulo"]} — {info["artista"]}' + (f'  [omitida: {error}]' if error else ''), flush=True)

    r = preparar(_conexion_cli(), args.ids or None, args.forzar, avance)
    print(json.dumps(r, ensure_ascii=False))
    print(f'Listo en {time.time() - inicio:.0f} s')


if __name__ == '__main__':
    sys.exit(main())
