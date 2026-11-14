from recomendacion.sucursales import repartir, tiendas_por_producto


def test_repartir_proporcional_y_completo():
    ciudades = [{'geoid': 'a', 'poblacion': 600}, {'geoid': 'b', 'poblacion': 300}, {'geoid': 'c', 'poblacion': 100}]
    assert repartir(ciudades, 10) == {'a': 6, 'b': 3, 'c': 1}
    # 7 tiendas: cuotas 4,2 / 2,1 / 0,7; los restos mayores se llevan las sobrantes
    assert repartir(ciudades, 7) == {'a': 4, 'b': 2, 'c': 1}


def test_tiendas_por_producto_logaritmico():
    assert tiendas_por_producto(20, 20, 100000) == 5
    assert tiendas_por_producto(100000, 20, 100000) == 40
    assert tiendas_por_producto(10**7, 20, 100000) == 40
    assert 5 < tiendas_por_producto(1000, 20, 100000) < 40
