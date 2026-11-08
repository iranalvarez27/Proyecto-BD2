import json
import re

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
