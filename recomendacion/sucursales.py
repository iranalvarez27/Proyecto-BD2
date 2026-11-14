"""Sucursales simuladas en EE. UU., repartidas por poblacion con datos publicos del Census.

Ciudades (coordenadas y area): Gazetteer 2023. Poblacion: estimaciones 2023 por ciudad.
Ambos se cruzan por GEOID (estado + lugar).
"""
import csv
import io
import math
import random
import zipfile
from pathlib import Path

from data.preparar_amazon import descargar

RAIZ = Path(__file__).resolve().parents[1]
DIR_CENSUS = RAIZ / 'data' / 'raw' / 'census'
URL_GAZETTEER = ('https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/'
                 '2023_Gaz_place_national.zip')
URL_POBLACION = 'https://www2.census.gov/programs-surveys/popest/datasets/2020-2023/cities/totals/sub-est2023.csv'
N_TIENDAS = 1000
POBLACION_MINIMA = 50_000
SEMILLA = 42
SUFIJOS = (' city', ' town', ' village', ' CDP', ' borough', ' municipality', ' (balance)')
KM_POR_GRADO = 111.32


def ciudades(minimo=POBLACION_MINIMA, directorio=DIR_CENSUS) -> list[dict]:
    gazetteer, poblacion = directorio / 'gazetteer_places_2023.zip', directorio / 'poblacion_places_2023.csv'
    descargar(URL_GAZETTEER, str(gazetteer))
    descargar(URL_POBLACION, str(poblacion))
    habitantes = {}
    with open(poblacion, encoding='latin-1', newline='') as f:
        for fila in csv.DictReader(f):
            # 162 = ciudad incorporada (sin el desglose por condado)
            if fila['SUMLEV'] == '162':
                habitantes[fila['STATE'] + fila['PLACE']] = int(fila['POPESTIMATE2023'])
    resultado = []
    with zipfile.ZipFile(gazetteer) as z, z.open(z.namelist()[0]) as crudo:
        for fila in csv.DictReader(io.TextIOWrapper(crudo, encoding='latin-1'), delimiter='\t'):
            fila = {k.strip(): v.strip() for k, v in fila.items()}
            pob = habitantes.get(fila['GEOID'], 0)
            if pob >= minimo:
                nombre = fila['NAME']
                for sufijo in SUFIJOS:
                    nombre = nombre.removesuffix(sufijo)
                resultado.append({'geoid': fila['GEOID'], 'ciudad': nombre, 'estado': fila['USPS'], 'poblacion': pob,
                                  'lat': float(fila['INTPTLAT']), 'lon': float(fila['INTPTLONG']),
                                  'area_km2': float(fila['ALAND_SQMI']) * 2.59})
    return sorted(resultado, key=lambda c: c['geoid'])


def repartir(ciudades, n=N_TIENDAS) -> dict:
    """Tiendas por ciudad proporcionales a la poblacion (metodo del resto mayor)."""
    total = sum(c['poblacion'] for c in ciudades)
    cuotas = {c['geoid']: n * c['poblacion'] / total for c in ciudades}
    asignadas = {g: int(q) for g, q in cuotas.items()}
    restos = sorted(cuotas, key=lambda g: (-(cuotas[g] - asignadas[g]), g))
    for g in restos[:n - sum(asignadas.values())]:
        asignadas[g] += 1
    return {g: q for g, q in asignadas.items() if q}


def tiendas(n=N_TIENDAS, semilla=SEMILLA, directorio=DIR_CENSUS) -> list[dict]:
    """Ubicacion de cada tienda: dispersa alrededor del centro de su ciudad, segun el area."""
    lista = ciudades(directorio=directorio)
    por_ciudad = repartir(lista, n)
    resultado = []
    for c in lista:
        cantidad = por_ciudad.get(c['geoid'], 0)
        azar = random.Random(f"{semilla}-{c['geoid']}")
        radio_km = math.sqrt(c['area_km2'] / math.pi)
        for i in range(cantidad):
            # radio * sqrt(u) reparte uniforme dentro del circulo
            r, ang = radio_km * math.sqrt(azar.random()) * 0.8, azar.uniform(0, 2 * math.pi)
            lat = c['lat'] + r * math.sin(ang) / KM_POR_GRADO
            lon = c['lon'] + r * math.cos(ang) / (KM_POR_GRADO * math.cos(math.radians(c['lat'])))
            sufijo = f' #{i + 1}' if cantidad > 1 else ''
            resultado.append({'nombre': f"Tecno Store {c['ciudad']}, {c['estado']}{sufijo}", 'ciudad': c['ciudad'],
                              'estado': c['estado'], 'lat': round(lat, 6), 'lon': round(lon, 6)})
    for tid, t in enumerate(resultado, 1):
        t['id'] = tid
    return resultado


def tiendas_por_producto(num_resenas, minimo_resenas, maximo_resenas, menos=5, mas=40) -> int:
    """De 5 a 40 tiendas, en escala logaritmica de la cantidad de resenas."""
    if maximo_resenas <= minimo_resenas:
        return menos
    t = (math.log(max(num_resenas, minimo_resenas)) - math.log(minimo_resenas)) / (
        math.log(maximo_resenas) - math.log(minimo_resenas))
    return round(menos + (mas - menos) * min(1.0, t))
