from concurrent.futures import ThreadPoolExecutor
import pytest

from recomendacion.compras import comprar, preparar_compras
from recomendacion.preparar import asegurar_tabla
from recomendacion.repositorio import Repositorio
from text.ingesta import abrir_motor


@pytest.fixture
def motor(tmp_path):
    c = abrir_motor(str(tmp_path))
    asegurar_tabla(c, 'ecommerce_productos', 'id INT PRIMARY KEY, subcategoria VARCHAR(30), precio_centavos INT')
    r = Repositorio(c)
    r.insertar('ecommerce_productos', [1, 'audio', 1000])
    r.insertar('ecommerce_productos', [2, 'audio', 2000])
    preparar_compras(c)
    r.insertar('ecommerce_inventario', [1, 1, 1, 1])
    r.insertar('ecommerce_inventario', [2, 2, 1, 0])
    yield c
    c.pool.close_all()


ITEM = {'producto_id': 1, 'tienda_id': 1, 'cantidad': 1}


def test_reintento_idempotente(motor):
    primero = comprar(motor, 500, 'solicitud-1', [ITEM])
    assert comprar(motor, 500, 'solicitud-1', [ITEM]) == primero
    assert Repositorio(motor).ejecutar('SELECT stock FROM ecommerce_inventario WHERE id = 1')[0]['stock'] == 0
    with pytest.raises(ValueError):
        comprar(motor, 501, 'solicitud-1', [ITEM])


def test_cesta_fallida_revierte_todas_las_lineas(motor):
    with pytest.raises(ValueError):
        comprar(motor, 500, 'fallida', [ITEM, {**ITEM, 'producto_id': 2}])
    assert Repositorio(motor).ejecutar('SELECT stock FROM ecommerce_inventario WHERE id = 1')[0]['stock'] == 1
    assert not Repositorio(motor).ejecutar("SELECT id FROM ecommerce_operaciones WHERE solicitud = 'fallida'")


def test_dos_compras_concurrentes_del_ultimo_producto(motor):
    def intento(i):
        try:
            return comprar(motor, 500 + i, f'concurrente-{i}', [ITEM])
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(intento, [1, 2]))
    assert sum(r is not None for r in resultados) == 1
    assert Repositorio(motor).ejecutar('SELECT stock FROM ecommerce_inventario WHERE id = 1')[0]['stock'] == 0


def test_compra_en_vivo_equivale_a_recalcular(tmp_path):
    from recomendacion.afinidades import cargar_base, contar, puntaje
    c = abrir_motor(str(tmp_path))
    asegurar_tabla(c, 'ecommerce_productos', 'id INT PRIMARY KEY, subcategoria VARCHAR(30), precio_centavos INT')
    preparar_compras(c)
    r = Repositorio(c)
    base = [{1, 2}, {1, 3}, {2, 3, 4}]
    cargar_base(r, base)
    from recomendacion.afinidades import registrar_compra
    registrar_compra(r, set(), [2, 3])
    compradores, soportes = contar(base + [{2, 3}])
    for (a, b), soporte in soportes.items():
        fila = r.ejecutar(f'SELECT score, soporte FROM ecommerce_afinidades WHERE producto_origen = {a} AND producto_destino = {b}')
        assert fila[0]['soporte'] == soporte
        if 1 not in (a, b):
            assert abs(fila[0]['score'] - puntaje(soporte, compradores[a], compradores[b])) < 1e-9
    c.pool.close_all()
