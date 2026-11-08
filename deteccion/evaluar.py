import argparse
import csv
import hashlib
import platform
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np

from deteccion.detector import Detector, Parametros
from deteccion.experimento import modificar
from multimedia import bovw, config
from multimedia.mfcc import cargar_audio


def ruta_local(ruta):
    ruta = str(ruta).replace('\\', '/')
    if ruta.startswith('/app/'):
        return config.RAIZ / ruta[5:]
    p = Path(ruta)
    return p if p.is_absolute() else config.RAIZ / p


def leer_rutas(ruta):
    with open(ruta, encoding='utf-8', newline='') as f:
        return {str(d['id']): ruta_local(d['ruta']) for d in csv.DictReader(f)}


def resumen(filas):
    salida = []
    for mod in dict.fromkeys(f['modificacion'] for f in filas):
        grupo = [f for f in filas if f['modificacion'] == mod]
        positivos = [f for f in grupo if f['esperado'] is not None]
        negativos = [f for f in grupo if f['esperado'] is None]
        salida.append({
            'modificacion': mod, 'positivos': len(positivos), 'negativos': len(negativos),
            'recall_pista': (sum(f['acierto_pista'] for f in positivos) / len(positivos)) if positivos else None,
            'recall_localizacion': (sum(f['acierto_posicion'] for f in positivos) / len(positivos)) if positivos else None,
            'tasa_consultas_con_pista_incorrecta': sum(f['pista_incorrecta'] for f in grupo) / len(grupo),
            'fpr_negativos': (sum(f['detectado'] for f in negativos) / len(negativos)) if negativos else None,
            'latencia_media_ms': float(np.mean([f['tiempo_ms'] for f in grupo])),
        })
    return salida


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-n', type=int, default=10000)
    ap.add_argument('--pistas', type=int, default=20)
    ap.add_argument('--negativas', type=int, default=10)
    ap.add_argument('--dur', type=float, default=10)
    ap.add_argument('--semilla', type=int, default=42)
    ap.add_argument('--particion', choices=['calibracion', 'prueba'], default='prueba')
    ap.add_argument('--umbral', type=float, default=.65)
    ap.add_argument('--umbral-secuencia', type=float, default=.60)
    ap.add_argument('--k', type=int, default=100)
    ap.add_argument('--min-votos', type=int, default=2)
    ap.add_argument('--representacion', choices=['boaw', 'raiz', 'hibrida'], default='hibrida')
    ap.add_argument('--metodo', choices=['EXACTO', 'HNSW', 'IVF'], default='EXACTO')
    ap.add_argument('--sin-reduccion-ruido', action='store_true')
    ap.add_argument('--salida', default='bench/results/audio_c')
    args = ap.parse_args(argv)
    if args.pistas < 1 or args.negativas < 0 or not 5 <= args.dur <= 20:
        ap.error('pistas >= 1, negativas >= 0 y dur entre 5 y 20')
    import librosa
    version_codigo = hashlib.sha256(
        (config.RAIZ / 'deteccion/detector.py').read_bytes() +
        (config.RAIZ / 'multimedia/mfcc.py').read_bytes()).hexdigest()
    rng = np.random.default_rng(args.semilla)
    vectores, ids = bovw.cargar_coleccion('audio', args.n)
    ext = bovw._extractor('audio', args.n)
    params = Parametros(umbral=args.umbral, k=args.k, min_votos=args.min_votos,
                        representacion=args.representacion, metodo=args.metodo, umbral_secuencia=args.umbral_secuencia, reducir_ruido=not args.sin_reduccion_ruido)
    rutas = leer_rutas(config.RAIZ / 'bench/data/fma/objetos.csv')
    detector = Detector(vectores, ids, ext, params, resolver_original=lambda pid: rutas[pid])
    pistas = sorted({str(o[0]) for o in ids})
    rng.shuffle(pistas)

    corte = len(pistas) // 2
    pool = pistas[:corte] if args.particion == 'calibracion' else pistas[corte:]
    existentes = {(str(o[0]), int(o[1])) for o in ids}
    filas, omitidos = [], []
    for pid in pool:
        if sum(f['modificacion'] == 'ninguna' for f in filas) >= args.pistas:
            break
        try:
            y = cargar_audio(rutas[pid], detector.sr)

            max_seg = max(s for p, s in existentes if p == pid)
            limite = min(len(y) / detector.sr, (max_seg + 1) * detector.seg_s)
            if limite <= args.dur + .5:
                raise ValueError('pista sin suficientes segundos indexados')
            inicio = float(rng.uniform(.1, limite - args.dur))
            a = int(inicio * detector.sr)
            inicio = a / detector.sr
            frag = y[a:a + int(args.dur * detector.sr)]
            for mod in ('ninguna', 'ruido', 'volumen', 'tempo'):
                fm, factor = modificar(frag, mod, rng)
                resultado = detector.detectar(fm)
                eventos = resultado['coincidencias']
                correctos = [e for e in eventos if e['track_id'] == pid]
                error_posicion = min((abs(e['original_inicio_s'] - (inicio + factor * e['inicio_s'])) for e in correctos), default=None)
                localizado = error_posicion is not None and error_posicion <= 1.0
                filas.append(dict(esperado=pid, modificacion=mod, inicio_original_s=inicio,
                                  detectado=bool(eventos), acierto_pista=bool(correctos),
                                  acierto_posicion=localizado, error_posicion_s=error_posicion,
                                  pista_incorrecta=any(e['track_id'] != pid for e in eventos),
                                  tiempo_ms=resultado['metricas']['tiempo_ms'], coincidencias=eventos))
                print(pid, mod, 'OK' if correctos else 'MISS', 'otros', sum(e['track_id'] != pid for e in eventos), flush=True)
        except (OSError, ValueError, KeyError) as ex:
            omitidos.append({'track_id': pid, 'error': str(ex)})

    ruta_neg = config.RAIZ / 'bench/data/fma/consultas.csv'
    negativos = {}
    if ruta_neg.exists():
        with open(ruta_neg, encoding='utf-8', newline='') as f:
            negativos = {str(d['track_id']): ruta_local(d['ruta']) for d in csv.DictReader(f)}
    fuera = sorted(p for p in negativos if p not in set(pistas))
    rng.shuffle(fuera)
    mitad = len(fuera) // 2
    fuera = fuera[:mitad] if args.particion == 'calibracion' else fuera[mitad:]
    for pid in fuera:
        if sum(f['esperado'] is None for f in filas) >= args.negativas:
            break
        try:
            y = cargar_audio(negativos[pid], detector.sr)
            if len(y) < args.dur * detector.sr:
                raise ValueError('audio negativo demasiado corto')
            inicio = int(rng.uniform(0, len(y) - args.dur * detector.sr))
            r = detector.detectar(y[inicio:inicio + int(args.dur * detector.sr)])
            filas.append(dict(esperado=None, track_id_negativo=pid, modificacion='fuera_de_coleccion',
                              detectado=r['posible_coincidencia'], acierto_pista=False,
                              acierto_posicion=False, pista_incorrecta=r['posible_coincidencia'],
                              tiempo_ms=r['metricas']['tiempo_ms'], coincidencias=r['coincidencias']))
            print('negativo', pid, 'FP' if r['posible_coincidencia'] else 'OK', flush=True)
        except (OSError, ValueError) as ex:
            omitidos.append({'track_id': pid, 'error': str(ex)})
    if not filas:
        raise SystemExit('No se pudo evaluar ningun audio real; revise rutas y coleccion')
    metricas = resumen(filas)
    destino = Path(args.salida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.with_suffix('.json').write_text(json.dumps({
        'n_coleccion': args.n, 'semilla': args.semilla, 'particion': args.particion,
        'codigo_sha256': version_codigo, 'tolerancia_localizacion_s': 1.0,
        'versiones': {'python': platform.python_version(), 'numpy': np.__version__, 'librosa': librosa.__version__},
        'parametros': asdict(params), 'modelo': ext.meta,
        'solicitados': {'positivos': args.pistas, 'negativos': args.negativas},
        'resumen': metricas, 'consultas': filas, 'omitidos': omitidos,
        'nota': 'Recall de identificacion de pista, distinto de Recall@k de vecinos ANN. Similitud no equivale a probabilidad.',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    with destino.with_suffix('.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(metricas[0]))
        w.writeheader(); w.writerows(metricas)
    print(json.dumps(metricas, indent=2), flush=True)
    if sum(f['modificacion'] == 'ninguna' for f in filas) < args.pistas or sum(f['esperado'] is None for f in filas) < args.negativas:
        raise SystemExit('Evaluacion incompleta: se guardaron los resultados parciales y las omisiones')


if __name__ == '__main__':
    main()
