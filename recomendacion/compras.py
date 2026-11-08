"""Eventos y compras idempotentes con inventario protegido por transacciones."""
from collections import defaultdict
import hashlib
import json
import random
import time

from recomendacion.afinidades import refrescar
from recomendacion.preparar import asegurar_tabla
from recomendacion.repositorio import Repositorio, literal

ESQUEMAS = {
    'ecommerce_interacciones': 'id BIGINT PRIMARY KEY, usuario_id INT, producto_id INT, tipo VARCHAR(16), fecha BIGINT, origen VARCHAR(24)',
    'ecommerce_afinidades': 'id BIGINT PRIMARY KEY, producto_origen INT, producto_destino INT, score DOUBLE, soporte INT',
    'ecommerce_inventario': 'id BIGINT PRIMARY KEY, producto_id INT, tienda_id INT, stock INT',
    'ecommerce_operaciones': 'id BIGINT PRIMARY KEY, solicitud VARCHAR(64), usuario_id INT, firma VARCHAR(64), respuesta VARCHAR(3000)',
    'ecommerce_estado': 'id INT PRIMARY KEY, revision BIGINT',
}
TABLAS_COMPRA = sorted(ESQUEMAS)


def siguiente_id(repo, tabla):
    filas = repo.ejecutar(f'SELECT id FROM {tabla} ORDER BY id DESC LIMIT 1')
    return filas[0]['id'] + 1 if filas else 1


def preparar_compras(conexion):
    repo = Repositorio(conexion)
    for tabla, esquema in ESQUEMAS.items():
        asegurar_tabla(conexion, tabla, esquema)
    for tabla, columna in [('ecommerce_interacciones', 'usuario_id'), ('ecommerce_afinidades', 'producto_origen'),
                           ('ecommerce_inventario', 'producto_id'), ('ecommerce_operaciones', 'solicitud')]:
        if not conexion.catalog.tiene_indice(tabla, columna):
            repo.ejecutar(f'CREATE INDEX ON {tabla} ({columna}) USING HASH')
    with repo.transaccion(TABLAS_COMPRA):
        if not repo.ejecutar('SELECT * FROM ecommerce_estado WHERE id = 1'):
            repo.insertar('ecommerce_estado', [1, 0])
        eventos = repo.ejecutar("SELECT id FROM ecommerce_interacciones WHERE origen = 'simulado_semilla'")
        if not eventos:
            productos = repo.ejecutar('SELECT id, subcategoria FROM ecommerce_productos ORDER BY id')
            grupos = defaultdict(list)
            for p in productos:
                grupos[p['subcategoria']].append(p['id'])
            grupos = list(grupos.values())
            azar = random.Random(42)
            nuevo = siguiente_id(repo, 'ecommerce_interacciones')
            for usuario in range(1, 201):
                grupo = grupos[(usuario - 1) % len(grupos)]
                cesta = set(azar.sample(grupo, min(3, len(grupo))))
                cesta.add(azar.choice(productos)['id'])
                for pid in sorted(cesta):
                    repo.insertar('ecommerce_interacciones', [nuevo, usuario, pid, 'compra', 1700000000000 + nuevo, 'simulado_semilla'])
                    nuevo += 1
        refrescar(repo)


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
        version = refrescar(repo)
        resultado = {'solicitud': solicitud, 'items': items, 'total_centavos': total, 'moneda': 'USD',
                     'version_afinidades': version, 'simulada': True}
        repo.insertar('ecommerce_operaciones', [siguiente_id(repo, 'ecommerce_operaciones'), solicitud, usuario_id, firma,
                                               json.dumps(resultado, separators=(',', ':'))])
    return resultado
