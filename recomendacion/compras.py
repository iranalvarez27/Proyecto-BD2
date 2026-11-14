"""Eventos y compras idempotentes con inventario protegido por transacciones."""
import hashlib
import json
import time

from recomendacion.afinidades import cargar_base, leer_compras, registrar_compra
from recomendacion.preparar import asegurar_tabla
from recomendacion.repositorio import Repositorio, literal

ESQUEMAS = {
    'ecommerce_interacciones': 'id BIGINT PRIMARY KEY, usuario_id INT, producto_id INT, tipo VARCHAR(16), fecha BIGINT, origen VARCHAR(24)',
    'ecommerce_afinidades': 'id BIGINT PRIMARY KEY, producto_origen INT, producto_destino INT, score DOUBLE, soporte INT',
    'ecommerce_compradores': 'id INT PRIMARY KEY, compradores INT',
    'ecommerce_inventario': 'id BIGINT PRIMARY KEY, producto_id INT, tienda_id INT, stock INT',
    'ecommerce_operaciones': 'id BIGINT PRIMARY KEY, solicitud VARCHAR(64), usuario_id INT, firma VARCHAR(64), respuesta VARCHAR(3000)',
    'ecommerce_estado': 'id INT PRIMARY KEY, revision BIGINT',
}
TABLAS_COMPRA = sorted(ESQUEMAS)


def siguiente_id(repo, tabla):
    filas = repo.ejecutar(f'SELECT id FROM {tabla} ORDER BY id DESC LIMIT 1')
    return filas[0]['id'] + 1 if filas else 1


def preparar_compras(conexion, ruta_compras=None):
    """Tablas de compras; la base de afinidades sale de las compras reales de ruta_compras."""
    repo = Repositorio(conexion)
    if not conexion.catalog.existe_tabla('ecommerce_estado') or not repo.ejecutar('SELECT * FROM ecommerce_estado WHERE id = 1'):
        # carga interrumpida o primera vez: la base se rehace entera
        for tabla in ('ecommerce_afinidades', 'ecommerce_compradores'):
            if conexion.catalog.existe_tabla(tabla):
                repo.ejecutar(f'DROP TABLE {tabla}')
    for tabla, esquema in ESQUEMAS.items():
        asegurar_tabla(conexion, tabla, esquema)
    for tabla, columna in [('ecommerce_interacciones', 'usuario_id'), ('ecommerce_afinidades', 'producto_origen'),
                           ('ecommerce_inventario', 'producto_id'), ('ecommerce_operaciones', 'solicitud')]:
        if not conexion.catalog.tiene_indice(tabla, columna):
            repo.ejecutar(f'CREATE INDEX ON {tabla} ({columna}) USING HASH')
    if repo.ejecutar('SELECT * FROM ecommerce_estado WHERE id = 1'):
        return
    if ruta_compras is not None:
        cargar_base(repo, leer_compras(ruta_compras))
    repo.insertar('ecommerce_estado', [1, 0])


def registrar_interaccion(conexion, usuario_id, producto_id, tipo):
    if tipo not in ('vista', 'carrito'):
        raise ValueError('El evento debe ser vista o carrito')
    repo = Repositorio(conexion)
    with repo.transaccion(['ecommerce_interacciones']):
        if not repo.ejecutar(f'SELECT id FROM ecommerce_productos WHERE id = {producto_id}'):
            raise LookupError('Producto inexistente')
        nuevo = siguiente_id(repo, 'ecommerce_interacciones')
        repo.insertar('ecommerce_interacciones', [nuevo, usuario_id, producto_id, tipo, int(time.time() * 1000), 'demo_usuario'])
    return {'id': nuevo, 'tipo': tipo}


def comprar(conexion, usuario_id, solicitud, items):
    if not items or len(items) > 20:
        raise ValueError('La compra debe contener entre 1 y 20 líneas')
    if len({(i['producto_id'], i['tienda_id']) for i in items}) != len(items):
        raise ValueError('Agrupe las cantidades de las líneas repetidas')
    firma = hashlib.sha256(json.dumps(sorted(items, key=lambda i: (i['producto_id'], i['tienda_id'])), sort_keys=True).encode()).hexdigest()
    repo = Repositorio(conexion)
    with repo.transaccion(TABLAS_COMPRA):
        previas = repo.ejecutar(f'SELECT * FROM ecommerce_operaciones WHERE solicitud = {literal(solicitud)}')
        if previas:
            previa = previas[0]
            if previa['usuario_id'] != usuario_id or previa['firma'] != firma:
                raise ValueError('La clave de solicitud ya pertenece a otra compra')
            return json.loads(previa['respuesta'])
        previos = {r['producto_id'] for r in repo.ejecutar(
            f"SELECT producto_id, tipo FROM ecommerce_interacciones WHERE usuario_id = {int(usuario_id)}") if r['tipo'] == 'compra'}
        nuevo_evento = siguiente_id(repo, 'ecommerce_interacciones')
        total = 0
        for item in items:
            pid, tienda, cantidad = item['producto_id'], item['tienda_id'], item['cantidad']
            if cantidad < 1:
                raise ValueError('Cantidad inválida')
            inventario = repo.ejecutar(f'SELECT * FROM ecommerce_inventario WHERE producto_id = {pid} AND tienda_id = {tienda}')
            if len(inventario) != 1 or inventario[0]['stock'] < cantidad:
                raise ValueError(f'Stock insuficiente para el producto {pid} en la tienda {tienda}')
            producto = repo.ejecutar(f'SELECT precio_centavos FROM ecommerce_productos WHERE id = {pid}')
            if not producto:
                raise LookupError('Producto inexistente')
            fila = inventario[0]
            repo.ejecutar(f'UPDATE ecommerce_inventario SET stock = {fila["stock"] - cantidad} WHERE id = {fila["id"]}')
            repo.insertar('ecommerce_interacciones', [nuevo_evento, usuario_id, pid, 'compra', int(time.time() * 1000), 'demo_usuario'])
            nuevo_evento += 1
            total += cantidad * producto[0]['precio_centavos']
        registrar_compra(repo, previos, [item['producto_id'] for item in items])
        version = nuevo_evento - 1
        repo.ejecutar(f'UPDATE ecommerce_estado SET revision = {version} WHERE id = 1')
        resultado = {'solicitud': solicitud, 'items': items, 'total_centavos': total, 'moneda': 'USD',
                     'version_afinidades': version, 'simulada': True}
        repo.insertar('ecommerce_operaciones', [siguiente_id(repo, 'ecommerce_operaciones'), solicitud, usuario_id, firma,
                                               json.dumps(resultado, separators=(',', ':'))])
    return resultado
