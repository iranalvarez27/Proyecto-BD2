from recomendacion.preparar import asegurar_tabla
from recomendacion.repositorio import Repositorio
from recomendacion.disponibilidad import tiendas_con_stock
from text.ingesta import abrir_motor


def test_knn_continua_hasta_tienda_con_stock(tmp_path):
    c = abrir_motor(str(tmp_path))
    r = Repositorio(c)
    asegurar_tabla(c, 'ecommerce_tiendas', 'id INT PRIMARY KEY, nombre VARCHAR(30), ubicacion POINT')
    asegurar_tabla(c, 'ecommerce_inventario', 'id INT PRIMARY KEY, producto_id INT, tienda_id INT, stock INT')
    for i in range(1, 9):
        r.ejecutar(f"INSERT INTO ecommerce_tiendas VALUES ({i}, 'Tienda {i}', POINT({-12 + i * .01}, -77))")
    r.ejecutar('CREATE INDEX ON ecommerce_tiendas (ubicacion) USING RTREE')
    r.insertar('ecommerce_inventario', [1, 1, 8, 3])
    try:
        tiendas = tiendas_con_stock(r, 1, -12, -77)
        assert [t['id'] for t in tiendas] == [8]
        assert tiendas[0]['stock'] == 3
        assert any('rtree' in paso for t in r.trazas for paso in t['plan'])
        assert tiendas_con_stock(r, 2, -12, -77) == []
    finally:
        c.pool.close_all()
