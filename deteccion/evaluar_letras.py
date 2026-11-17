"""Prueba automática de la canción cantada por letra: 5 canciones de géneros distintos x 2 tipos de consulta.

  (a) 15 s de la voz separada (simula cantar a capela)
  (b) 15 s de la canción original (simula cantar sobre la pista)

Cada consulta debe devolver la canción correcta y un tramo de la original a ±10 s del fragmento usado
(o el mismo pasaje de otra repetición del estribillo). Resultado en bench/results/letras.json.

  python -m deteccion.evaluar_letras [--ids ID ...] [--salida ruta.json]
"""
import json
from pathlib import Path
import sys
import time

import librosa
import numpy as np

from deteccion import acapella, letras

DURACION_S = 15.0
TOLERANCIA_S = 10.0
GENEROS = ('cumbia', 'rock', 'pop / balada', 'chicha', 'rock / balada')
SALIDA = acapella.RAIZ / 'bench' / 'results' / 'letras.json'


def canciones_por_id(ids):
    return [(t, json.loads((letras.carpeta_letras() / f'{t}.json').read_text(encoding='utf-8'))['frases']) for t in ids]


def elegir_canciones(catalogo):
    elegidas = []
    for genero in GENEROS:
        mejores = []
        for tid, meta in catalogo.items():
            ruta = letras.carpeta_letras() / f'{tid}.json'
            if meta.get('genero') != genero or not ruta.is_file():
                continue
            frases = json.loads(ruta.read_text(encoding='utf-8'))['frases']
            util = sum(len(letras.palabras_utiles(f[2])) for f in frases)
            mejores.append((util, tid, frases))
        if mejores:
            util, tid, frases = max(mejores)
            elegidas.append((tid, frases))
    return elegidas


def ventana(frases):
    mejor, inicio = -1, 0.0
    for _ini, _fin, _t in frases:
        t0 = _ini
        palabras = sum(len(letras.palabras_utiles(t)) for a, b, t in frases if a >= t0 and b <= t0 + DURACION_S)
        if palabras > mejor:
            mejor, inicio = palabras, t0
    return inicio


def similar(frases, inicio, o_ini, o_fin):
    real = {p for a, b, x in frases if a >= inicio and b <= inicio + DURACION_S for p in letras.palabras_utiles(x)}
    hallado = {p for a, b, x in frases if a >= o_ini - 1 and b <= o_fin + 1 for p in letras.palabras_utiles(x)}
    return bool(real) and len(real & hallado) / len(real) >= 0.6


def evaluar(conexion=None, verbose=True, ids=None):
    catalogo = acapella.cargar_catalogo()
    if conexion is None:
        conexion = letras._conexion_cli()
    casos = []
    for tid, frases in (canciones_por_id(ids) if ids else elegir_canciones(catalogo)):
        meta = catalogo[tid]
        inicio = ventana(frases)
        origen = {'voz': acapella.directorio_modelo() / 'voces' / f'{tid}.flac',
                  'original': acapella.RAIZ / meta['ruta']}
        for tipo, ruta in origen.items():
            y, _ = librosa.load(str(ruta), sr=16000, mono=True, offset=inicio, duration=DURACION_S)
            t0 = time.perf_counter()
            r = letras.detectar(np.asarray(y, dtype=np.float32), 16000, conexion)
            segundos = time.perf_counter() - t0
            c = r['coincidencias'][0] if r['coincidencias'] else None
            cancion = bool(c and c['track_id'] == tid)
            exacto = bool(cancion and c['original_inicio_s'] - TOLERANCIA_S <= inicio + DURACION_S
                          and c['original_fin_s'] + TOLERANCIA_S >= inicio)
            repetido = bool(cancion and not exacto and similar(frases, inicio, c['original_inicio_s'], c['original_fin_s']))
            acierto = exacto or repetido
            fila = {'track_id': tid, 'titulo': meta['titulo'], 'genero': meta['genero'], 'consulta': tipo,
                    'inicio_real_s': round(inicio, 1), 'cancion_correcta': cancion, 'tramo_exacto': exacto, 'tramo_por_estribillo': repetido,
                    'acierto': acierto, 'segundos': round(segundos, 1),
                    'detectado': f"{c['titulo']} ({c['original_inicio_s']}-{c['original_fin_s']} s, {c['porcentaje_similitud']}%)" if c else None,
                    'texto': r['texto_reconocido'][:140]}
            casos.append(fila)
            if verbose:
                print(f"{'OK ' if acierto else 'FALLA'} {meta['genero']:14s} {meta['titulo'][:28]:28s} {tipo:8s} "
                      f"{segundos:5.1f} s  -> {fila['detectado']}", flush=True)
    resumen = {'consultas': len(casos), 'aciertos': sum(c['acierto'] for c in casos),
               'cancion_correcta': sum(c['cancion_correcta'] for c in casos), 'tramo_exacto': sum(c['tramo_exacto'] for c in casos),
               'segundos_medio': round(float(np.mean([c['segundos'] for c in casos])), 1) if casos else None}
    return {'resumen': resumen, 'casos': casos}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or '').strip().splitlines()[0])
    ap.add_argument('--ids', nargs='+', help='track_id de las canciones a probar (por defecto, la de letra más completa de cada género)')
    ap.add_argument('--salida', default=str(SALIDA))
    args = ap.parse_args(argv)
    informe = evaluar(ids=args.ids)
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(informe['resumen']))
    return 0 if informe['resumen']['aciertos'] == informe['resumen']['consultas'] else 1


if __name__ == '__main__':
    sys.exit(main())
