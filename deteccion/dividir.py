import argparse
import os
import shutil
from pathlib import Path

import numpy as np

FUENTES = {
    'Colección propia': ('musica_propia', 'Perú e internacional'),
    'FMA': ('todas_fma_small', 'FMA'),
}


def dividir(n_total=None, forzar=False) -> list:
    from backend.audio_detection import leer_metadatos
    from backend.engine_adapter import EngineAdapter
    from bench.datasets.fma_todas import publicar_tabla
    from multimedia import bovw, cache, colecciones_audio as ca, config

    data_dir = Path(os.environ.get('BD2_DATA_DIR', 'data'))
    n_total = n_total or bovw.n_coleccion_vigente('audio')
    info = ca.informacion(n_total)
    if info.get('alcance') != 'biblioteca_musical':
        raise SystemExit(f'La colección {n_total} no es la Biblioteca musical unificada (alcance={info.get("alcance")})')
    metas, _ = leer_metadatos(EngineAdapter(data_dir=str(data_dir)), ca.tabla(n_total, info), True)
    vectores, ids = bovw.cargar_coleccion('audio', n_total)
    origen = config.directorio_coleccion('audio', n_total)
    salida = []
    for fuente, (alcance, etiqueta) in FUENTES.items():
        pistas = [dict(track_id=pid, genero=m['genero'], titulo=m['titulo'], artista=m['artista'], ruta=m['ruta'],
                       fuente=m['fuente'], id_origen=m['id_origen'])
                  for pid, m in metas.items() if m['fuente'] == fuente]
        if not pistas:
            print(f'[dividir] sin pistas de la fuente {fuente!r}; se omite')
            continue
        conjunto = {p['track_id'] for p in pistas}
        mascara = np.array([str(o[0]) in conjunto for o in ids])
        n = int(mascara.sum())
        carpeta = config.directorio_coleccion('audio', n)
        if carpeta.exists() and not forzar:
            raise SystemExit(f'Ya existe la colección {n}; usa --forzar para rehacerla')
        shutil.rmtree(carpeta, ignore_errors=True)
        carpeta.mkdir(parents=True)
        bovw._guardar_npy(carpeta / 'vectores.npy', vectores[mascara])
        bovw._guardar_npy(carpeta / 'ids.npy', cache.crear_array_ids([ids[i] for i in np.flatnonzero(mascara)]),
                          allow_pickle=True)
        shutil.copy2(origen / 'idf.npy', carpeta / 'idf.npy')
        sub = {k: v for k, v in info.items() if k not in ('descriptores', 'huella_coleccion')}
        sub.update(N=n, alcance=alcance, tabla=f'audios_{n}', nombre=etiqueta, canciones=len(pistas),
                   fuentes=[{'n': n, 'tabla': f'audios_{n}', 'nombre': etiqueta, 'canciones': len(pistas),
                             'segmentos': n}],
                   dividida_de=n_total, huella_coleccion=f'dividida-de-{n_total}')
        bovw._guardar_json(carpeta / 'coleccion.json', sub)
        print(f'[dividir] {etiqueta}: {len(pistas)} canciones, {n} segmentos -> tabla audios_{n}', flush=True)
        publicar_tabla(pistas, n, data_dir, 'EXACTO', track_id_texto=True, con_procedencia=True, carga_masiva=True)
        salida.append((etiqueta, n, len(pistas)))
    return salida


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-n', type=int, default=None, help='colección unificada (por defecto, la más grande)')
    ap.add_argument('--forzar', action='store_true', help='rehace colecciones ya existentes')
    args = ap.parse_args(argv)
    for etiqueta, n, canciones in dividir(args.n, args.forzar):
        print(f'[dividir] listo: {etiqueta} (n={n}, {canciones} canciones)')


if __name__ == '__main__':
    main()
