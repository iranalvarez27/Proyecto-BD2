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
