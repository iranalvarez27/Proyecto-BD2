from recomendacion.catalogo import CATEGORIAS, clasificar, intercalar


def test_clasificar_por_prefijo_mas_largo():
    base = ['Electronics', 'Computers & Accessories']
    assert clasificar(base + ['Computers & Tablets', 'Laptops', 'Traditional Laptops']) == ('Laptops & Computers', 'Laptops')
    assert clasificar(base + ['Monitors']) == ('Monitors', 'Monitors')
    assert clasificar(base + ['Computer Accessories & Peripherals', 'Cables & Accessories']) is None
    assert clasificar([]) is None
    assert len(CATEGORIAS) == 9


def test_intercalar_turnos_por_subcategoria():
    grupos = {'b': [1, 2, 3], 'a': [10]}
    assert intercalar(grupos) == [10, 1, 2, 3]


def test_cupos_con_tope_comun():
    from recomendacion.catalogo import cupos
    assert cupos({'a': 100, 'b': 10, 'c': 1000}, 300) == {'a': 100, 'b': 10, 'c': 190}
    assert cupos({'a': 1448, 'b': 1726, 'c': 11778, 'd': 3968}, 30000) == {'a': 1448, 'b': 1726, 'c': 11778, 'd': 3968}
    r = cupos({'chica': 5, 'grande': 100, 'media': 100}, 105)
    assert r == {'chica': 5, 'grande': 50, 'media': 50}
