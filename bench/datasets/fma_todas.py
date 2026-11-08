import argparse
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import tempfile
import time


def huella(ruta):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b''):
            h.update(bloque)
    return h.hexdigest()


def inventario(dir_fma, variante, metadatos):
    carpeta = Path(dir_fma) / ('fma_' + variante)
    pistas = []
    vistos = set()
    for ruta in sorted(carpeta.rglob('*.mp3')):
        if not ruta.stem.isdigit():
            raise ValueError('MP3 sin identificador FMA numerico: ' + str(ruta))
        tid = int(ruta.stem)
        if tid in vistos:
            raise ValueError('track_id duplicado: ' + str(tid))
        vistos.add(tid)
        pistas.append({**metadatos.get(tid, {'track_id': tid, 'titulo': 'Track ' + str(tid),
                                             'artista': '', 'genero': 'Unknown'}),
                       'ruta': str(ruta.resolve())})
    if not pistas:
        raise ValueError('No hay MP3 locales en ' + str(carpeta))
    return pistas


def fuentes_utilizables(objetos, manifiesto):
    return [oid for oid, _ in objetos if manifiesto.get(str(oid), {}).get('estado') == 'ok']


def publicar_tabla(pistas, n, data_dir, metodo, *, track_id_texto=False,
                   nombre_tabla=None, con_procedencia=False, carga_masiva=False):
    from bench.datasets.fma import etiqueta_tamano, ingestar_tablas_audio
    from query import catalog_store
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    tabla = nombre_tabla or 'audios_' + etiqueta_tamano(n)
    with tempfile.TemporaryDirectory(prefix='fma_todas_', dir=data_dir) as temporal:
        opciones = {'track_id_texto': True} if track_id_texto else {}
        if nombre_tabla:
            opciones['nombre_tabla'] = nombre_tabla
        if con_procedencia:
            opciones['con_procedencia'] = True
        if carga_masiva:
            opciones['carga_masiva'] = True
        ingestar_tablas_audio(pistas, [n], temporal, metodo_indice=metodo, **opciones)
        entrada = catalog_store.leer(temporal)['tablas'][tabla]
        archivos = [p for p in Path(temporal).iterdir() if p.is_file() and p.name.startswith(tabla + '_') or
                    p.is_file() and p.name == tabla + '.bin']
        existentes = [data_dir / p.name for p in archivos if (data_dir / p.name).exists()]
        if existentes:
            copia = data_dir / 'backups' / ('fma_todas_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
            copia.mkdir(parents=True, exist_ok=True)
            for archivo in existentes:
                shutil.copy2(archivo, copia / archivo.name)
        for archivo in archivos:
            os.replace(archivo, data_dir / archivo.name)
        catalogo = catalog_store.leer(str(data_dir))
        catalogo['tablas'][tabla] = entrada
        catalog_store.escribir(str(data_dir), catalogo)
    return tabla


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--variante', choices=['small', 'medium'], default='small')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--indice', choices=['EXACTO', 'HNSW', 'IVF'], default='HNSW')
    ap.add_argument('--dir-fma', default='bench/data/fma')
    ap.add_argument('--data-dir', default='data')
    ap.add_argument('--reintentar-errores', action='store_true')
    args = ap.parse_args(argv)
    if args.workers < 1:
        ap.error('workers debe ser positivo')
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = str(args.workers)
    import numpy as np
    from bench.datasets.fma import leer_metadatos_tracks, guardar_pistas_csv, guardar_segmentos_csv, segmentos_de_coleccion
    from multimedia import bovw, cache, codebook, config, histogramas
    from query import catalog_store

    inicio = time.perf_counter()
    dir_fma = Path(args.dir_fma).resolve()
    data_dir = Path(args.data_dir).resolve()
    modelo = config.directorio_modelo('audio')
    meta = codebook.cargar_meta('audio')
    codebook.validar_meta(meta, 'audio')
    params = {k: meta[k] for k in config.parametros('audio')}
    cache_dir = modelo / 'cache'
    info_cache = cache.resumen_cache('audio')
    if info_cache.get('params') != params:
        raise ValueError('El modelo y la cache tienen parametros diferentes')
    pistas = inventario(dir_fma, args.variante,
                        leer_metadatos_tracks(dir_fma / 'fma_metadata/tracks.csv'))
    objetos = [(str(p['track_id']), p['ruta']) for p in pistas]
    guardar_pistas_csv(dir_fma / 'objetos_todas.csv', pistas)
    protegidos = [modelo / 'meta.json', modelo / 'codebook.npy', modelo / 'estandarizacion.npz']
    protegidos += list((modelo / 'colecciones').glob('*/vectores.npy'))
    protegidos += list((modelo / 'colecciones').glob('*/ids.npy'))
    antes = {str(p): huella(p) for p in protegidos}
    copia = data_dir / 'backups' / ('fma_todas_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    copia.mkdir(parents=True, exist_ok=True)
    for nombre in ('manifiesto.json', 'cache.json'):
        if (cache_dir / nombre).exists():
            shutil.copy2(cache_dir / nombre, copia / nombre)
    if (data_dir / 'catalog.json').exists():
        shutil.copy2(data_dir / 'catalog.json', copia / 'catalog.json')
    print('[todas] MP3 locales:', len(pistas), '| vocabulario conservado:', meta['huella_codebook'], flush=True)
    resumen_cache = cache.sincronizar('audio', objetos, directorio=cache_dir,
                                      workers=args.workers, shard=int(info_cache['shard']),
                                      reintentar_errores=args.reintentar_errores,
                                      compactar_auto=False, **params)
    manifiesto = cache.manifiesto('audio')
    ids = cache.expandir_ids('audio', fuentes_utilizables(objetos, manifiesto))
    if not ids:
        raise ValueError('Ningun audio produjo segmentos utilizables')
    n = len(ids)
    presentes = {str(oid[0]) for oid in ids}
    exclusiones = [{'track_id': p['track_id'], 'ruta': p['ruta'],
                    'motivo': manifiesto.get(str(p['track_id']), {}).get('error') or 'Sin segmentos completos'}
                   for p in pistas if str(p['track_id']) not in presentes]
    print('[todas] Canciones utilizables:', len(presentes), '| segmentos:', n,
          '| exclusiones:', len(exclusiones), flush=True)
    ruta_info = modelo / 'colecciones' / str(n) / 'coleccion.json'
    info_previa = json.loads(ruta_info.read_text(encoding='utf-8')) if ruta_info.exists() else {}
    print('[todas] Cuantizando descriptores con el codebook existente...', flush=True)
    hist = histogramas.actualizar_histogramas('audio', ids)
    print('[todas] Histogramas:', hist, flush=True)
    coleccion = bovw.construir_coleccion('audio', n, ids=ids)
    vectores, ids_guardados = bovw.cargar_coleccion('audio', n)
    if len(ids_guardados) != n or not np.isfinite(vectores).all():
        raise ValueError('La coleccion generada es inconsistente')
    assert set(ids) == set(ids_guardados)
    info = json.loads(ruta_info.read_text(encoding='utf-8'))
    info.update(alcance='todas_fma_' + args.variante, canciones=len(presentes),
                archivos_locales=len(pistas), exclusiones=len(exclusiones))
    bovw._guardar_json(ruta_info, info)
    from backend.audio_detection import tabla_audio
    tabla = tabla_audio(n)
    existente = catalog_store.leer(str(data_dir))['tablas'].get(tabla)
    if not (existente and info_previa.get('huella_coleccion') == info['huella_coleccion']):
        print('[todas] Construyendo tabla e indice', args.indice, 'en staging...', flush=True)
        publicar_tabla(pistas, n, data_dir, args.indice)
    for otra in (modelo / 'colecciones').glob('*/coleccion.json'):
        if otra == ruta_info:
            continue
        anterior = json.loads(otra.read_text(encoding='utf-8'))
        if anterior.get('alcance') == info['alcance']:
            anterior['alcance'] = 'historico_' + anterior['alcance']
            bovw._guardar_json(otra, anterior)
    por_track = {str(p['track_id']): p for p in pistas}
    guardar_segmentos_csv(dir_fma / 'segmentos_todas.csv', segmentos_de_coleccion(ids_guardados, por_track))
    cambios = [p for p, h in antes.items() if huella(p) != h]
    if cambios:
        raise ValueError('Se alteraron artefactos anteriores: ' + str(cambios))
    reporte = {'fecha_utc': datetime.now(timezone.utc).isoformat(), 'variante': args.variante,
               'archivos_locales': len(pistas), 'canciones_indexadas': len(presentes),
               'segmentos_indexados': n, 'tabla': tabla, 'indice': args.indice,
               'huella_codebook': meta['huella_codebook'], 'vocabulario_reutilizado': True,
               'colecciones_anteriores_intactas': True, 'exclusiones': exclusiones,
               'cache': resumen_cache, 'segundos': round(time.perf_counter() - inicio, 2)}
    bovw._guardar_json(dir_fma / 'indexacion_todas.json', reporte)
    print(json.dumps(reporte, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    mp.freeze_support()
    main()
