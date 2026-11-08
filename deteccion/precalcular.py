import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import os
import time

from backend.audio_detection import leer_metadatos
from backend.engine_adapter import EngineAdapter
from deteccion.chroma import chroma_original
from deteccion.detector import Detector, Parametros
from multimedia import bovw, colecciones_audio, config
from multimedia.colecciones_audio import huella_archivo, ruta_local


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-n', type=int, default=None, help='tamaño de la colección (por defecto, la más grande)')
    ap.add_argument('--hilos', type=int, default=min(4, os.cpu_count() or 1))
    args = ap.parse_args(argv)

    n = args.n or bovw.n_coleccion_vigente('audio')
    engine = EngineAdapter(data_dir=os.environ.get('BD2_DATA_DIR', 'data'))
    tabla = colecciones_audio.tabla(n)
    metas, _ = leer_metadatos(engine, tabla, bool(colecciones_audio.informacion(n).get('con_procedencia')))
    extractor = bovw._extractor('audio', n)
    carpeta_cromas = Path(extractor.directorio) / 'cromas'
    detector = Detector(None, None, extractor, Parametros(), busqueda=SimpleNamespace(ids=()),
                        resolver_original=lambda pid: ruta_local(metas[pid]['ruta']))

    def preparar(pid):
        detector._leer_original(pid)
        ruta = ruta_local(metas[pid]['ruta'])
        chroma_original(str(ruta), huella_archivo(ruta), str(carpeta_cromas))

    pistas = list(metas)
    print(f'[precalcular] {len(pistas):,} pistas de {tabla} (n={n}), {args.hilos} hilos', flush=True)
    inicio, fallos = time.perf_counter(), []
    with ThreadPoolExecutor(args.hilos) as pool:
        for i, (pid, resultado) in enumerate(zip(pistas, pool.map(lambda p: _seguro(preparar, p), pistas)), 1):
            if resultado is not None:
                fallos.append((pid, resultado))
            if i % 50 == 0 or i == len(pistas):
                print(f'[precalcular] {i:,}/{len(pistas):,} · {time.perf_counter() - inicio:.0f} s', flush=True)
    for pid, motivo in fallos[:10]:
        print(f'[precalcular] omitida {pid}: {motivo}')
    print(f'[precalcular] listo: {len(pistas) - len(fallos):,} pistas en caché, {len(fallos)} omitidas')


def _seguro(funcion, pid):
    try:
        funcion(pid)
    except (OSError, ValueError, KeyError, RuntimeError) as ex:
        return str(ex)


if __name__ == '__main__':
    main()
