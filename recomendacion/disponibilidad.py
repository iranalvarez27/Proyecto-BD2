"""Inventario reproducible y búsqueda R-Tree restringida a sucursales con stock."""
import random

from recomendacion.preparar import asegurar_tabla
from recomendacion.repositorio import Repositorio

SUCURSALES = [
    (1, 'Tecno Lima · Miraflores', -12.1211, -77.0297),
    (2, 'Tecno Lima · San Isidro', -12.0977, -77.0365),
    (3, 'Tecno Lima · Centro', -12.0464, -77.0428),
    (4, 'Tecno Lima · Surco', -12.1450, -76.9917),
    (5, 'Tecno Lima · Los Olivos', -11.9920, -77.0708),
    (6, 'Tecno Lima · San Miguel', -12.0773, -77.0907),
    (7, 'Tecno Lima · Barranco', -12.1494, -77.0219),
    (8, 'Tecno Lima · La Molina', -12.0876, -76.9372),
]


def preparar_inventario(conexion):
    asegurar_tabla(conexion, 'ecommerce_tiendas', 'id INT PRIMARY KEY, nombre VARCHAR(100), ubicacion POINT')
    repo = Repositorio(conexion)
    for pid, nombre, lat, lon in SUCURSALES:
        if not repo.ejecutar(f'SELECT id FROM ecommerce_tiendas WHERE id = {pid}'):
            from recomendacion.repositorio import literal
            repo.ejecutar(f'INSERT INTO ecommerce_tiendas VALUES ({pid}, {literal(nombre)}, POINT({lat}, {lon}))')
    if not conexion.catalog.tiene_indice('ecommerce_tiendas', 'ubicacion'):
        repo.ejecutar('CREATE INDEX ON ecommerce_tiendas (ubicacion) USING RTREE')
    with repo.transaccion(['ecommerce_inventario']):
        existentes = {r['id'] for r in repo.ejecutar('SELECT id FROM ecommerce_inventario')}
        for p in repo.ejecutar('SELECT id FROM ecommerce_productos ORDER BY id'):
            azar = random.Random(42 + p['id'])
            for tienda in sorted(azar.sample(range(1, 9), 3)):
                clave = p['id'] * 100 + tienda
                if clave not in existentes:
                    repo.insertar('ecommerce_inventario', [clave, p['id'], tienda, azar.randint(0, 12)])


def tiendas_con_stock(repo, pid, lat=None, lon=None, k=5):
    filas = repo.ejecutar(f'SELECT tienda_id, stock FROM ecommerce_inventario WHERE producto_id = {int(pid)} AND stock > 0')
    inventario = {r['tienda_id']: r['stock'] for r in filas}
    if not inventario:
        return []
    ids = ','.join(str(i) for i in sorted(inventario))
    columnas = 'id, nombre, ubicacion'
    orden = f'ORDER BY id LIMIT {int(k)}'
    if lat is not None and lon is not None:
        distancia = f'distancia_haversine(ubicacion, POINT({float(lat)}, {float(lon)}))'
        columnas += f', {distancia} AS dist_m'
        orden = f'ORDER BY {distancia} LIMIT {int(k)}'
    filas = repo.ejecutar(f'SELECT {columnas} FROM ecommerce_tiendas WHERE id IN ({ids}) {orden}')
    return [{**r, 'stock': inventario[r['id']], 'simulada': True} for r in filas]
