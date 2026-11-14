"""Sucursales en EE. UU. con R-Tree, inventario reproducible y busqueda de tiendas cercanas."""
import csv
import random

from recomendacion.preparar import asegurar_tabla
from recomendacion.repositorio import Repositorio, literal

ESQUEMA_TIENDAS = 'id INT PRIMARY KEY, nombre VARCHAR(100), ciudad VARCHAR(60), estado VARCHAR(2), ubicacion POINT'
# id de inventario = producto * CLAVE + tienda (hasta 9999 tiendas)
CLAVE = 10_000
VERSION = 2


def _version(repo):
    if not repo.conexion.catalog.existe_tabla('ecommerce_estado'):
        return None
    filas = repo.ejecutar('SELECT revision FROM ecommerce_estado WHERE id = 2')
    return filas[0]['revision'] if filas else None


def preparar_inventario(conexion, productos_csv):
    """1000 tiendas del Census y, por producto, de 5 a 40 tiendas segun su popularidad."""
    from recomendacion import sucursales
    from recomendacion.compras import ESQUEMAS

    repo = Repositorio(conexion)
    if _version(repo) == VERSION:
        return
    # tiendas o inventario de otra version: se rehacen enteros
    for tabla in ('ecommerce_tiendas', 'ecommerce_inventario'):
        if conexion.catalog.existe_tabla(tabla):
            repo.ejecutar(f'DROP TABLE {tabla}')
    asegurar_tabla(conexion, 'ecommerce_tiendas', ESQUEMA_TIENDAS)
    asegurar_tabla(conexion, 'ecommerce_inventario', ESQUEMAS['ecommerce_inventario'])
    tiendas = sucursales.tiendas()
    for t in tiendas:
        repo.ejecutar(f"INSERT INTO ecommerce_tiendas VALUES ({t['id']}, {literal(t['nombre'])}, "
                      f"{literal(t['ciudad'])}, {literal(t['estado'])}, POINT({t['lat']}, {t['lon']}))")
    repo.ejecutar('CREATE INDEX ON ecommerce_tiendas (ubicacion) USING RTREE')

    with open(productos_csv, encoding='utf-8', newline='') as f:
        resenas = {int(p['id']): int(p['num_resenas']) for p in csv.DictReader(f)}
    minimo, maximo = min(resenas.values()), max(resenas.values())
    ids_tiendas = [t['id'] for t in tiendas]
    for pid in sorted(resenas):
        azar = random.Random(42 + pid)
        cantidad = sucursales.tiendas_por_producto(resenas[pid], minimo, maximo)
        for tienda in sorted(azar.sample(ids_tiendas, cantidad)):
            repo.insertar('ecommerce_inventario', [pid * CLAVE + tienda, pid, tienda, azar.randint(0, 12)])
    repo.ejecutar('CREATE INDEX ON ecommerce_inventario (producto_id) USING HASH')
    if _version(repo) is None:
        repo.insertar('ecommerce_estado', [2, VERSION])
    else:
        repo.ejecutar(f'UPDATE ecommerce_estado SET revision = {VERSION} WHERE id = 2')


COLUMNAS = 'id, nombre, ciudad, estado, ubicacion'


def _distancia(lat, lon):
    return f'distancia_haversine(ubicacion, POINT({float(lat)}, {float(lon)}))'


def tiendas_con_stock(repo, pid, lat=None, lon=None, k=5):
    filas = repo.ejecutar(f'SELECT tienda_id, stock FROM ecommerce_inventario WHERE producto_id = {int(pid)} AND stock > 0')
    inventario = {r['tienda_id']: r['stock'] for r in filas}
    if not inventario:
        return []
    ids = ','.join(str(i) for i in sorted(inventario))
    columnas, orden = COLUMNAS, f'ORDER BY id LIMIT {int(k)}'
    if lat is not None and lon is not None:
        columnas += f', {_distancia(lat, lon)} AS dist_m'
        orden = f'ORDER BY {_distancia(lat, lon)} LIMIT {int(k)}'
    filas = repo.ejecutar(f'SELECT {columnas} FROM ecommerce_tiendas WHERE id IN ({ids}) {orden}')
    return [{**r, 'stock': inventario[r['id']], 'simulada': True} for r in filas]


def tiendas_cercanas(repo, lat, lon, k=5):
    """Localizador: las k tiendas mas cercanas, k-NN sobre el R-Tree."""
    return repo.ejecutar(f'SELECT {COLUMNAS}, {_distancia(lat, lon)} AS dist_m FROM ecommerce_tiendas '
                         f'ORDER BY {_distancia(lat, lon)} LIMIT {int(k)}')


def todas_las_tiendas(repo):
    return repo.ejecutar(f'SELECT {COLUMNAS} FROM ecommerce_tiendas ORDER BY id')
