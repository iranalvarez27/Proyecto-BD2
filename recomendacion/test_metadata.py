import math

from recomendacion.metadata import gower, rango_log_precio


def ficha(sub, marca, precio):
    return {'subcategoria': sub, 'marca': marca, 'precio_centavos': precio}


def test_gower_promedia_atributos():
    rango = math.log(100)
    base = ficha('Earbuds', 'Sony', 1000)
    assert gower(base, ficha('Earbuds', 'sony', 1000), rango) == 1.0
    # otra subcategoria, otra marca, 10 veces el precio: solo aporta la mitad del precio
    assert abs(gower(base, ficha('Headphones', 'JBL', 10000), rango) - 0.5 / 3) < 1e-9


def test_marca_vacia_no_se_compara():
    rango = math.log(100)
    assert gower(ficha('Mice', '', 500), ficha('Mice', 'Logitech', 500), rango) == 1.0


def test_rango_logaritmico():
    assert abs(rango_log_precio([ficha('a', '', 100), ficha('b', '', 10000)]) - math.log(100)) < 1e-9
