import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time


ROOT = Path(__file__).resolve().parents[2]


def leer_catalogo(ruta):

    import soundfile as sf
    ruta = Path(ruta).resolve()
    pistas, vistos, archivos = [], set(), set()
    with ruta.open(encoding='utf-8-sig', newline='') as f:
        lector = csv.DictReader(f)
        requeridos = {'track_id', 'track_name', 'artists', 'file'}
        if not requeridos.issubset(lector.fieldnames or []):
            raise ValueError('El catalogo requiere: ' + ', '.join(sorted(requeridos)))
        for numero, fila in enumerate(lector, 2):
            tid = fila['track_id'].strip()
            audio = (ruta.parent / fila['file']).resolve()
            if not tid or len(tid.encode('utf-8')) > 64 or tid in vistos:
                raise ValueError(f'Fila {numero}: track_id vacio, duplicado o demasiado largo')
            if not audio.is_relative_to(ruta.parent) or not audio.is_file():
                raise ValueError(f'Fila {numero}: audio ausente o fuera de la carpeta: {audio}')
            if audio in archivos:
                raise ValueError(f'Fila {numero}: archivo de audio repetido')
            info = sf.info(audio)
            if info.duration < 5:
                raise ValueError(f'Fila {numero}: audio menor de 5 segundos')
            vistos.add(tid)
            archivos.add(audio)
            pistas.append({'track_id': tid, 'titulo': fila['track_name'],
                           'artista': fila['artists'], 'genero': fila.get('track_genre', ''),
                           'ruta': str(audio), 'country': fila.get('country', ''),
                           'selection_group': fila.get('selection_group', ''),
                           'source_url': fila.get('source_url', ''),
                           'segmentos': int(info.duration // 2)})
    if not pistas:
        raise ValueError('El catalogo esta vacio')
    return pistas


def muestra_piloto(pistas):
    elegidas = []
    for artista in ('Grupo 5', 'Chacalón', 'Los Shapis', 'Libido', 'Pedro Suárez-Vértiz',
                    'Gian Marco', 'Agua Marina', 'Mar de Copas'):
        p = next((p for p in pistas if p['artista'] == artista), None)
        if p and p not in elegidas:
            elegidas.append(p)
    for p in pistas:
        if len(elegidas) >= 10:
            break
        if p not in elegidas:
            elegidas.append(p)
    return elegidas


def sha256(ruta):
    h = hashlib.sha256()
    with Path(ruta).open('rb') as f:
        for bloque in iter(lambda: f.read(1 << 20), b''):
            h.update(bloque)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--catalogo', default=str(ROOT / 'bench/data/musica_propia/catalogo.csv'))
    ap.add_argument('--data-dir', default=str(ROOT / 'data'))
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--piloto', action='store_true', help='solo 10 canciones de varios estilos')
    args = ap.parse_args(argv)
    if args.workers < 1:
        ap.error('workers debe ser positivo')

    for clave in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
        os.environ[clave] = '1'
    from multimedia import bovw, cache, codebook, config
    from bench.datasets.fma_todas import publicar_tabla
    from backend.audio_detection import tabla_audio
    from query import catalog_store
    import numpy as np

    inicio = time.perf_counter()
    catalogo = Path(args.catalogo).resolve()
    pistas = leer_catalogo(catalogo)
    total_catalogo = len(pistas)
    if args.piloto:
        pistas = muestra_piloto(pistas)
    modelo = config.directorio_modelo('audio')
    meta = codebook.cargar_meta('audio')
    codebook.validar_meta(meta, 'audio')
    params = {k: meta[k] for k in config.parametros('audio')}
    if float(params['seg_s']) != 2:
        raise ValueError('Este importador espera segmentos de 2 segundos')
    alcance = 'musica_propia_piloto' if args.piloto else 'musica_propia'


    existentes = cache.manifiesto('audio')
    for pista in pistas:
        previa = existentes.get(pista['track_id'])
        if previa and Path(previa.get('ruta', '')).resolve() != Path(pista['ruta']).resolve():
            if cache.huella_archivo(pista['ruta']) != previa.get('huella_archivo'):
                raise ValueError('El ID ya pertenece a otro audio en la cache: ' + pista['track_id'])
    protegidos = [modelo / nombre for nombre in ('meta.json', 'codebook.npy', 'estandarizacion.npz')
                  if (modelo / nombre).exists()]
    for ruta in (modelo / 'colecciones').glob('*/coleccion.json'):
        info = json.loads(ruta.read_text(encoding='utf-8'))
        if not str(info.get('alcance', '')).startswith('musica_propia'):
            protegidos.extend(ruta.parent / nombre for nombre in
                              ('coleccion.json', 'vectores.npy', 'ids.npy', 'idf.npy'))
    antes = {str(p): sha256(p) for p in protegidos}
    data_dir = Path(args.data_dir).resolve()
    copia = data_dir / 'backups' / ('musica_propia_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    copia.mkdir(parents=True)
    cache_dir = modelo / 'cache'
    for ruta in (data_dir / 'catalog.json', cache_dir / 'cache.json', cache_dir / 'manifiesto.json'):
        if ruta.exists():
            shutil.copy2(ruta, copia / ruta.name)
    shard = int(cache.resumen_cache('audio').get('shard', config.SHARD))
    objetos = [(p['track_id'], p['ruta']) for p in pistas]
    print(f'[propia] {len(pistas)} canciones; vocabulario existente {meta["huella_codebook"]}', flush=True)
    for desde in range(0, len(objetos), 50):
        cache.sincronizar('audio', objetos[desde:desde + 50], workers=args.workers,
                          shard=shard, compactar_auto=False, reintentar_errores=True, **params)
        print(f'[propia] Extraccion {min(desde + 50, len(objetos))}/{len(objetos)}', flush=True)
    manifiesto = cache.manifiesto('audio')
    errores = [p['track_id'] for p in pistas
               if manifiesto.get(p['track_id'], {}).get('estado') != 'ok']
    if errores:
        raise ValueError('No se publica una coleccion incompleta; errores: ' + str(errores))
    ids = cache.expandir_ids('audio', [p['track_id'] for p in pistas])
    if {str(oid[0]) for oid in ids} != {p['track_id'] for p in pistas}:
        raise ValueError('Hay canciones sin segmentos')
    n = len(ids)
    ruta_info = modelo / 'colecciones' / str(n) / 'coleccion.json'
    previa = json.loads(ruta_info.read_text(encoding='utf-8')) if ruta_info.exists() else {}
    tabla = tabla_audio(n)
    if (previa and previa.get('alcance') != alcance) or (
            not previa and tabla in catalog_store.leer(str(data_dir))['tablas']):
        raise ValueError(f'El tamano {n} ya pertenece a otra coleccion; no se sobrescribira')
    print(f'[propia] Construyendo BoAW de {n} segmentos...', flush=True)
    bovw.construir_coleccion('audio', n, ids=ids)
    vectores, guardados = bovw.cargar_coleccion('audio', n)
    if list(guardados) != ids or not np.isfinite(vectores).all():
        raise ValueError('Vectores o IDs inconsistentes')
    print('[propia] Publicando tabla SQL con IDs de texto...', flush=True)
    publicar_tabla(pistas, n, data_dir, 'EXACTO', track_id_texto=True)
    info = json.loads(ruta_info.read_text(encoding='utf-8'))
    info.update(alcance=alcance, canciones=len(pistas),
                nombre='Música propia' + (' · piloto' if args.piloto else ''),
                fuente='Colección local · Perú e internacional',
                catalogo=str(catalogo.relative_to(ROOT)) if catalogo.is_relative_to(ROOT) else str(catalogo),
                revision_grabaciones='pendiente_revision_manual')
    bovw._guardar_json(ruta_info, info)
    cambios = [p for p, huella in antes.items() if sha256(p) != huella]
    if cambios:
        raise ValueError('Se modificaron artefactos protegidos: ' + str(cambios))
    reporte = {'fecha_utc': datetime.now(timezone.utc).isoformat(), 'coleccion': alcance,
               'canciones': len(pistas), 'catalogo_total': total_catalogo, 'segmentos': n,
               'tabla': tabla, 'vocabulario_reutilizado': True,
               'colecciones_anteriores_intactas': True, 'huella_codebook': meta['huella_codebook'],
               'segundos': round(time.perf_counter() - inicio, 2),
               'originales_necesarios': 'Conservar audios: la verificacion de secuencia y reproduccion los consultan.'}
    destino = catalogo.parent / ('indexacion_piloto.json' if args.piloto else 'indexacion.json')
    bovw._guardar_json(destino, reporte)
    print(json.dumps(reporte, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    mp.freeze_support()
    main()
