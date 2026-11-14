"""Similitud de Gower (1971) entre fichas de producto: promedio de similitudes por atributo.

Categoricos (subcategoria, marca): 1 si coinciden, 0 si no; un atributo vacio en alguna de
las dos fichas no se compara. Precio: 1 - |ln a - ln b| / rango de ln(precio) del catalogo,
en escala logaritmica porque el precio varia en ordenes de magnitud.
"""
import math


def rango_log_precio(productos) -> float:
    precios = [p['precio_centavos'] for p in productos if p['precio_centavos'] > 0]
    return math.log(max(precios)) - math.log(min(precios)) if precios else 0.0


def gower(a, b, rango: float) -> float:
    partes = [float(a['subcategoria'] == b['subcategoria'])]
    if a['marca'] and b['marca']:
        partes.append(float(a['marca'].casefold() == b['marca'].casefold()))
    if rango > 0 and a['precio_centavos'] > 0 and b['precio_centavos'] > 0:
        distancia = abs(math.log(a['precio_centavos']) - math.log(b['precio_centavos']))
        partes.append(1 - distancia / rango)
    return sum(partes) / len(partes)
