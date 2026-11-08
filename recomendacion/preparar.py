"""Preparación offline y reanudable del catálogo Amazon por ASIN.

Ejecutar con el backend detenido para compartir los archivos del motor.
"""
import argparse
from collections import defaultdict
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

from recomendacion.repositorio import Repositorio

RAIZ = Path(__file__).resolve().parents[1]
ESQUEMAS = {
    'ecommerce_productos': 'id INT PRIMARY KEY, asin VARCHAR(24), nombre VARCHAR(240), categoria VARCHAR(120), subcategoria VARCHAR(120), marca VARCHAR(120), precio_centavos INT, moneda VARCHAR(3), rating DOUBLE',
    'ecommerce_textos': 'id INT PRIMARY KEY, contenido VARCHAR(3500)',
    'ecommerce_imagenes_hnsw': 'id INT PRIMARY KEY, ruta VARCHAR(400)',
    'ecommerce_imagenes_ivf': 'id INT PRIMARY KEY, ruta VARCHAR(400)',
}


def guardar_json(ruta, valor):
    temporal = ruta.with_suffix('.tmp')
    temporal.write_text(json.dumps(valor, ensure_ascii=False, indent=2), encoding='utf-8')
    temporal.replace(ruta)


def manifiesto(data_dir):
    ruta = Path(data_dir) / 'ecommerce_manifest.json'
    return json.loads(ruta.read_text()) if ruta.exists() else None


def seleccionar(productos_csv, imagenes_dir, n, anteriores=()):
    import cv2
    from text.ingesta import recortar_utf8

    grupos = defaultdict(list)
    por_asin = {}
    with open(productos_csv, encoding='utf-8', newline='') as archivo:
        for producto in csv.DictReader(archivo):
            asin = producto['asin']
            ruta = Path(imagenes_dir) / f'{asin}.jpg'
            if asin in por_asin or not ruta.is_file():
                continue
            precio = Decimal(producto['precio'])
            if not precio.is_finite() or precio <= 0:
                continue
            producto['ruta'] = ruta.resolve().relative_to(RAIZ).as_posix()
            por_asin[asin] = producto
            grupos[producto['subcategoria']].append(asin)
    elegidos = list(anteriores)
    if any(asin not in por_asin for asin in elegidos):
        raise ValueError('El origen perdió productos ya preparados. Restaure la fuente antes de ampliar.')
    vistos = set(elegidos)
    listas = [sorted(grupos[c]) for c in sorted(grupos)]
    posicion = 0
    while len(elegidos) < n and any(posicion < len(g) for g in listas):
        for grupo in listas:
            if posicion >= len(grupo) or len(elegidos) >= n:
                continue
            asin = grupo[posicion]
            if asin in vistos:
                continue
            if cv2.imread(str(RAIZ / por_asin[asin]['ruta'])) is None:
                continue
            elegidos.append(asin)
            vistos.add(asin)
        posicion += 1
    if len(elegidos) < n:
        raise ValueError(f'Solo hay {len(elegidos)} productos con imagen válida, se solicitaron {n}')
    filas = []
    for pid, asin in enumerate(elegidos, 1):
        p = por_asin[asin]
        contenido = ' '.join(p[c] for c in ('nombre', 'descripcion', 'caracteristicas') if p[c])
        filas.append({
            'id': pid, 'asin': asin,
            'producto': [pid, asin, recortar_utf8(p['nombre'], 240), recortar_utf8(p['categoria'], 120),
                         recortar_utf8(p['subcategoria'], 120), recortar_utf8(p['marca'], 120),
                         int((Decimal(p['precio']) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)),
                         'USD', float(p['rating'] or 0)],
            'texto': [pid, recortar_utf8(contenido, 3500)], 'imagen': [pid, p['ruta']],
            'texto_recortado': len(contenido.encode('utf-8')) > 3500,
        })
    return filas


def asegurar_tabla(conexion, nombre, esquema):
    if not conexion.catalog.existe_tabla(nombre):
        Repositorio(conexion).ejecutar(f'CREATE TABLE {nombre} ({esquema})')


def preparar_catalogo(conexion, productos_csv, imagenes_dir, n):
    anterior = manifiesto(conexion.data_dir)
    if anterior and n < len(anterior['asins']):
        raise ValueError('La ampliación debe conservar todos los productos existentes')
    filas = seleccionar(productos_csv, imagenes_dir, n, anterior['asins'] if anterior else ())
    firma = hashlib.sha256(json.dumps(filas, sort_keys=True).encode()).hexdigest()
    if anterior and anterior.get('firma_catalogo') == firma and anterior.get('catalogo_listo'):
        return anterior
    # Una preparación interrumpida queda explícitamente fuera de servicio hasta reanudarla.
    estado = {'version': 1, 'asins': [f['asin'] for f in filas], 'firma_catalogo': firma,
              'catalogo_listo': False, 'indices_listos': False, 'idioma': 'english',
              'moneda': 'USD', 'origen': 'Amazon Reviews 2023 Electronics',
              'textos_recortados': sum(f['texto_recortado'] for f in filas)}
    ruta = Path(conexion.data_dir) / 'ecommerce_manifest.json'
    guardar_json(ruta, estado)
    repo = Repositorio(conexion)
    for tabla, esquema in ESQUEMAS.items():
        asegurar_tabla(conexion, tabla, esquema)
        existentes = {r['id']: list(r.values()) for r in repo.ejecutar(f'SELECT * FROM {tabla}')}
        campo = 'producto' if tabla == 'ecommerce_productos' else 'texto' if tabla == 'ecommerce_textos' else 'imagen'
        for fila in filas:
            valores = fila[campo]
            actual = existentes.get(fila['id'])
            if actual is not None and actual != valores:
                raise ValueError(f'El producto {fila["asin"]} cambió en {tabla}. Se requiere migración explícita.')
            if actual is None:
                repo.insertar(tabla, valores)
    estado['catalogo_listo'] = True
    guardar_json(ruta, estado)
    return estado


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--productos', default='data/amazon/productos.csv')
    parser.add_argument('--imagenes', default='bench/data/amazon_img/imgs')
    parser.add_argument('--size', type=int, default=1000)
    args = parser.parse_args()
    if args.size < 1:
        parser.error('--size debe ser positivo')
    from text.ingesta import abrir_motor
    conexion = abrir_motor(args.data_dir)
    try:
        resultado = preparar_catalogo(conexion, args.productos, args.imagenes, args.size)
        print(json.dumps({'productos': len(resultado['asins']), 'catalogo_listo': True}))
    finally:
        conexion.pool.close_all()


if __name__ == '__main__':
    main()
