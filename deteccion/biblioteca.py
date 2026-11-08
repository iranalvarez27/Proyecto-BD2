import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from multimedia import colecciones_audio, config
from multimedia.colecciones_audio import clave_relativa, huella_archivo, ruta_local

VERSION = 1
MODELO_FIJO = ('meta.json', 'codebook.npy', 'estandarizacion.npz')
URL_POR_DEFECTO = 'https://github.com/iranalvarez27/Proyecto-BD2/releases/download/biblioteca-audio-10k/biblioteca-10k.tar.gz'
SHA256_POR_DEFECTO = 'e8cf0d66fe3366cc225a2afb3bb0ef13103c61f74c9312ec3999bbe19d9968b5'
_RELEASES = 'https://github.com/iranalvarez27/Proyecto-BD2/releases/download/'
PUBLICADAS = {
    '10k': (URL_POR_DEFECTO, SHA256_POR_DEFECTO),
    'peru': (_RELEASES + 'biblioteca-audio-peru/biblioteca-peru.tar.gz',
             '137f20a21ee111370151d2a94a6ec38d18420bcbf6552eee82756d951e5e75ba'),
    'fma': (_RELEASES + 'biblioteca-audio-fma/biblioteca-fma.tar.gz',
            '475c13f563707a505cbfcda7d651e168f8e4835f700ac321b5deff40fd087c1d'),
}
RAICES = ('data', 'modelo', 'audio')


def _data_dir() -> Path:
    return Path(os.environ.get('BD2_DATA_DIR', 'data'))


def _destinos() -> dict:
    return {'data': _data_dir(), 'modelo': config.directorio_modelo('audio'), 'audio': Path(config.RAIZ)}


def _agregar_bytes(tar, nombre, datos: bytes) -> None:
    info = tarfile.TarInfo(nombre)
    info.size, info.mtime = len(datos), time.time()
    tar.addfile(info, io.BytesIO(datos))


def crear_paquete(destino, archivos: dict, manifest: dict, catalogo: dict) -> int:
    with tarfile.open(destino, 'w:gz', compresslevel=6) as tar:
        _agregar_bytes(tar, 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=1).encode('utf-8'))
        _agregar_bytes(tar, 'catalogo.json', json.dumps(catalogo, ensure_ascii=False).encode('utf-8'))
        for nombre, ruta in archivos.items():
            tar.add(ruta, arcname=nombre, recursive=False)
    return Path(destino).stat().st_size


def exportar(n, destino, con_audio=False, con_indice=False) -> dict:
    from backend.audio_detection import leer_metadatos
    from backend.engine_adapter import EngineAdapter
    from deteccion.chroma import ruta_cache_chroma
    from deteccion.detector import ruta_cache_secuencia
    from multimedia import bovw
    from query import catalog_store

    data_dir, modelo = _data_dir(), config.directorio_modelo('audio')
    tabla, info = colecciones_audio.tabla(n), colecciones_audio.informacion(n)
    entrada = catalog_store.leer(str(data_dir))['tablas'].get(tabla)
    if entrada is None:
        raise SystemExit(f'La tabla {tabla} no existe en {data_dir}: construye primero la biblioteca de n={n}')
    metas, _ = leer_metadatos(EngineAdapter(data_dir=str(data_dir)), tabla, bool(info.get('con_procedencia')))
    extractor = bovw._extractor('audio', n)

    archivos = {f'data/{p.name}': p for patron in (tabla + '.*', tabla + '_*') for p in sorted(data_dir.glob(patron))
                if con_indice or '_vector.' not in p.name}
    for nombre in ('meta.json', 'codebook.npy', 'estandarizacion.npz'):
        archivos[f'modelo/{nombre}'] = modelo / nombre
    for p in sorted(config.directorio_coleccion('audio', n).iterdir()):
        archivos[f'modelo/colecciones/{n}/{p.name}'] = p

    huellas, sin_cache, sin_audio = {}, 0, 0
    for meta in metas.values():
        ruta = ruta_local(meta['ruta'])
        try:
            firma = huella_archivo(ruta)
        except FileNotFoundError:
            sin_audio += 1
            continue
        huellas[clave_relativa(ruta)] = firma
        for cache in (ruta_cache_secuencia(extractor, firma), ruta_cache_chroma(firma, modelo / 'cromas')):
            if cache.exists():
                archivos['modelo/' + cache.relative_to(modelo).as_posix()] = cache
            else:
                sin_cache += 1
        if con_audio and ruta.exists():
            archivos['audio/' + clave_relativa(ruta)] = ruta
    registro = Path(str(destino) + '.huellas.json')
    registro.write_text(json.dumps(huellas), encoding='utf-8')
    archivos[f'modelo/huellas/{tabla}.json'] = registro

    manifest = {'version': VERSION, 'n': n, 'tabla': tabla, 'pistas': len(metas), 'con_audio': con_audio,
                'archivos': len(archivos), 'sin_cache': sin_cache, 'sin_audio': sin_audio,
                'creado': datetime.now().isoformat(timespec='seconds')}
    try:
        manifest['bytes'] = crear_paquete(destino, archivos, manifest, {tabla: entrada})
    finally:
        registro.unlink(missing_ok=True)
    return manifest


def _descargar(url, destino: Path, sha256=None) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    h, leidos, siguiente = hashlib.sha256(), 0, 50 * 2 ** 20
    req = urllib.request.Request(url, headers={'User-Agent': 'minigestor-bd2'})
    with urllib.request.urlopen(req, timeout=60) as resp, open(destino, 'wb') as f:
        while True:
            bloque = resp.read(2 ** 20)
            if not bloque:
                break
            f.write(bloque)
            h.update(bloque)
            leidos += len(bloque)
            if leidos >= siguiente:
                print(f'[biblioteca] descargados {leidos / 2 ** 20:.0f} MB', flush=True)
                siguiente += 50 * 2 ** 20
    if sha256 and h.hexdigest().lower() != sha256.lower():
        destino.unlink(missing_ok=True)
        raise ValueError('la descarga no coincide con BIBLIOTECA_SHA256: paquete incompleto o alterado')
    return destino


def _fusionar_catalogo(data_dir: Path, catalogo: dict) -> None:
    from query import catalog_store
    contenido = catalog_store.leer(str(data_dir))
    contenido['tablas'].update(catalogo)
    catalog_store.escribir(str(data_dir), contenido)


def instalar_paquete(paquete, forzar=False) -> dict:
    destinos = _destinos()
    manifest = catalogo = None
    pendientes = []
    try:
        with tarfile.open(paquete, 'r:*') as tar:
            for miembro in tar:
                if not miembro.isfile():
                    continue
                if miembro.name in ('manifest.json', 'catalogo.json'):
                    datos = json.loads(tar.extractfile(miembro).read().decode('utf-8'))
                    if miembro.name == 'manifest.json':
                        manifest = datos
                        marca = destinos['data'] / f".biblioteca_{manifest['n']}.json"
                        if marca.exists() and not forzar and json.loads(marca.read_text('utf-8')).get('creado') == manifest['creado']:
                            print(f"[biblioteca] n={manifest['n']} ya estaba instalada (usa --forzar para reinstalar)")
                            return manifest
                    else:
                        catalogo = datos
                    continue
                raiz, _, resto = miembro.name.partition('/')
                if raiz not in destinos or not resto:
                    continue
                base = destinos[raiz].resolve()
                destino = (base / resto).resolve()
                if base not in destino.parents:
                    raise ValueError('ruta insegura en el paquete: ' + miembro.name)
                destino.parent.mkdir(parents=True, exist_ok=True)
                parcial = destino.with_name(destino.name + '.part')
                pendientes.append((parcial, destino))
                with tar.extractfile(miembro) as origen, open(parcial, 'wb') as salida:
                    shutil.copyfileobj(origen, salida)
                if (raiz == 'modelo' and resto in MODELO_FIJO and destino.exists() and not forzar
                        and destino.read_bytes() != parcial.read_bytes()):
                    raise ValueError(f'ya hay un modelo de audio distinto en {destino.parent}: instalar este paquete '
                                     'invalidaria las colecciones locales. Usa --forzar para reemplazarlo')
        if manifest is None or catalogo is None:
            raise ValueError('el archivo no es un paquete de biblioteca (falta manifest.json o catalogo.json)')
        for parcial, destino in pendientes:
            os.replace(parcial, destino)
    except BaseException:
        for parcial, _ in pendientes:
            parcial.unlink(missing_ok=True)
        raise
    _fusionar_catalogo(destinos['data'], catalogo)
    marca = destinos['data'] / f".biblioteca_{manifest['n']}.json"
    marca.write_text(json.dumps(manifest), encoding='utf-8')
    print(f"[biblioteca] instalada {manifest['tabla']} (n={manifest['n']}): {len(pendientes)} archivos, {manifest['pistas']} pistas")
    return manifest


def importar(origen, forzar=False, sha256=None) -> dict:
    if str(origen).startswith(('http://', 'https://')):
        temporal = _data_dir() / '.descarga_biblioteca.part'
        print(f'[biblioteca] descargando {origen}', flush=True)
        try:
            return instalar_paquete(_descargar(origen, temporal, sha256), forzar)
        finally:
            temporal.unlink(missing_ok=True)
    return instalar_paquete(origen, forzar)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='orden', required=True)
    ex = sub.add_parser('exportar', help='crea el paquete de una biblioteca')
    ex.add_argument('-n', type=int, default=None, help='tamaño de la colección (por defecto, la más grande)')
    ex.add_argument('-o', '--salida', default='biblioteca.tar.gz')
    ex.add_argument('--con-audio', action='store_true', help='incluye los MP3 originales (~0.8 GB para 10k)')
    ex.add_argument('--con-indice-vectorial', action='store_true',
                    help='incluye el indice vectorial de la tabla SQL (para SIMILAR_TO; la deteccion no lo necesita)')
    im = sub.add_parser('importar', help='instala un paquete desde una URL o un archivo')
    im.add_argument('origen', nargs='*', help='URL, archivo o atajo (' + ', '.join(PUBLICADAS) + '); '
                    'varios a la vez instalan varias fuentes; sin argumento, la biblioteca de 10k publicada')
    im.add_argument('--forzar', action='store_true')
    im.add_argument('--sha256', default=os.environ.get('BIBLIOTECA_SHA256'))
    args = ap.parse_args(argv)
    if args.orden == 'exportar':
        from multimedia import bovw
        n = args.n or bovw.n_coleccion_vigente('audio')
        m = exportar(n, args.salida, args.con_audio, args.con_indice_vectorial)
        print(f"[biblioteca] {args.salida}: {m['bytes'] / 2 ** 20:.0f} MB · {m['pistas']} pistas · {m['archivos']} archivos")
        if m['sin_cache']:
            print(f"[biblioteca] AVISO: {m['sin_cache']} cachés faltan; ejecuta antes `python -m deteccion.precalcular -n {n}`")
        if m['sin_audio']:
            print(f"[biblioteca] AVISO: {m['sin_audio']} pistas sin MP3 local: se omiten sus huellas")
        h = hashlib.sha256()
        with open(args.salida, 'rb') as f:
            for bloque in iter(lambda: f.read(2 ** 20), b''):
                h.update(bloque)
        print('[biblioteca] sha256:', h.hexdigest(), '(úsalo como BIBLIOTECA_SHA256 para verificar la descarga)')
    else:
        try:
            for origen in args.origen or [os.environ.get('BIBLIOTECA_URL') or URL_POR_DEFECTO]:
                url, sha = PUBLICADAS.get(origen, (origen, None))
                if origen == URL_POR_DEFECTO:
                    sha = SHA256_POR_DEFECTO
                importar(url, args.forzar, args.sha256 or sha)
        except (OSError, ValueError, tarfile.TarError) as ex:
            print(f'[biblioteca] no se pudo instalar: {ex}', file=sys.stderr)
            raise SystemExit(1)


if __name__ == '__main__':
    main()
