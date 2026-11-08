import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from . import config


def informacion(n):
    ruta = config.directorio_coleccion('audio', n) / 'coleccion.json'
    return json.loads(ruta.read_text(encoding='utf-8')) if ruta.exists() else {}


def tabla(n, info=None):
    info = informacion(n) if info is None else info
    nombre = info.get('tabla')
    if nombre:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', nombre):
            raise ValueError('Nombre de tabla de audio invalido')
        return nombre
    sufijo = str(n // 1000) + 'k' if n % 1000 == 0 else str(n)
    return 'audios_' + sufijo


def describir(n, info):
    alcance = info.get('alcance', '')
    unificada = alcance == 'biblioteca_musical'
    propia = alcance.startswith('musica_propia')
    completa = unificada or alcance.startswith('todas_fma_') or alcance == 'musica_propia'
    if unificada:
        nombre, fuente = 'Biblioteca musical', 'FMA + Perú e internacional'
    elif propia:
        nombre = 'Perú e internacional' + ('' if completa else ' · prueba piloto')
        fuente = 'Colección propia'
    else:
        nombre = 'FMA' + (' · catálogo completo' if completa else ' · muestra de evaluación')
        fuente = 'FMA'
    return dict(n=n, tabla=tabla(n, info), nombre=nombre, fuente=fuente,
                canciones=info.get('canciones'), completa=completa,
                propia=propia, unificada=unificada,
                fuentes=info.get('fuentes', []))


def normalizar_ruta(ruta):
    ruta = str(ruta).replace('\\', '/')
    return ruta[5:] if ruta.startswith('/app/') else ruta


def ruta_local(ruta, raiz=None):
    p = Path(normalizar_ruta(ruta))
    return p if p.is_absolute() else Path(raiz or config.RAIZ) / p


_BLOQUE_HUELLA = 65536


@lru_cache(maxsize=4096)
def _huella_contenido(ruta, mtime_ns, tamano):
    h = hashlib.sha1(str(tamano).encode())
    with open(ruta, 'rb') as f:
        h.update(f.read(_BLOQUE_HUELLA))
        if tamano > 2 * _BLOQUE_HUELLA:
            f.seek(tamano - _BLOQUE_HUELLA)
            h.update(f.read(_BLOQUE_HUELLA))
    return h.hexdigest()


def clave_relativa(ruta):
    p = Path(normalizar_ruta(ruta))
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.resolve().relative_to(Path(config.RAIZ).resolve()).as_posix()
    except ValueError:
        return p.name


def archivos_huellas():
    modelo = config.directorio_modelo('audio')
    return [p for p in [modelo / 'huellas.json', *sorted((modelo / 'huellas').glob('*.json'))] if p.is_file()]


@lru_cache(maxsize=4)
def _leer_huellas(firma):
    registro = {}
    for ruta, _mtime in firma:
        try:
            registro.update(json.loads(Path(ruta).read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
    return registro


def huella_archivo(ruta):
    p = Path(ruta)
    try:
        info = p.stat()
    except FileNotFoundError:
        try:
            firma = tuple((str(r), r.stat().st_mtime_ns) for r in archivos_huellas())
        except OSError:
            firma = ()
        huella = _leer_huellas(firma).get(clave_relativa(p))
        if huella is None:
            raise
        return huella
    return _huella_contenido(str(p), info.st_mtime_ns, info.st_size)
