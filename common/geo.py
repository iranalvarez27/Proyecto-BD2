import math

EARTH_RADIUS_M = 6371000.0
METROS_POR_GRADO = 111320.0

METRICA_HAVERSINE = "haversine"
METRICA_EUCLIDIANA = "euclidiana"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def euclidiana_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * METROS_POR_GRADO * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * METROS_POR_GRADO
    return math.sqrt(dx * dx + dy * dy)


def _separacion(valor: float, bajo: float, alto: float) -> float:
    """Distancia (>= 0) de ``valor`` al intervalo [bajo, alto]."""
    if valor < bajo:
        return bajo - valor
    if valor > alto:
        return valor - alto
    return 0.0


def mindist_haversine_m(lat: float, lon: float, mbr: tuple) -> float:
    lat_min, lon_min, lat_max, lon_max = mbr
    dlat = _separacion(lat, lat_min, lat_max)
    dlon = _separacion(lon, lon_min, lon_max)
    if dlat == 0.0 and dlon == 0.0:
        return 0.0
    cos_min = min(math.cos(math.radians(lat_min)), math.cos(math.radians(lat_max)))
    a = (math.sin(math.radians(dlat) / 2) ** 2
         + math.cos(math.radians(lat)) * max(0.0, cos_min) * math.sin(math.radians(dlon) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def mindist_euclidiana_m(lat: float, lon: float, mbr: tuple) -> float:
    lat_min, lon_min, lat_max, lon_max = mbr
    dlat = _separacion(lat, lat_min, lat_max)
    dlon = _separacion(lon, lon_min, lon_max)
    if dlat == 0.0 and dlon == 0.0:
        return 0.0
    cos_min = min(math.cos(math.radians((lat + lat_min) / 2)),
                  math.cos(math.radians((lat + lat_max) / 2)))
    dx = dlon * METROS_POR_GRADO * max(0.0, cos_min)
    dy = dlat * METROS_POR_GRADO
    return math.sqrt(dx * dx + dy * dy)


METRICAS = {
    METRICA_HAVERSINE: (haversine_m, mindist_haversine_m),
    METRICA_EUCLIDIANA: (euclidiana_m, mindist_euclidiana_m),
}


def resolver_metrica(metrica: str):
    try:
        return METRICAS[metrica]
    except KeyError:
        raise ValueError(f"metrica desconocida '{metrica}' (validas: {', '.join(METRICAS)})")


def punto_en_poligono(lat: float, lon: float, vertices: list) -> bool:
    dentro = False
    n = len(vertices)
    for i in range(n):
        lat1, lon1 = vertices[i]
        lat2, lon2 = vertices[(i + 1) % n]
        interseca = ((lon1 > lon) != (lon2 > lon)) and (
            lat < (lat2 - lat1) * (lon - lon1) / (lon2 - lon1) + lat1
        )
        if interseca:
            dentro = not dentro
    return dentro


def mbr_de_poligono(vertices: list) -> tuple:
    lats = [v[0] for v in vertices]
    lons = [v[1] for v in vertices]
    return (min(lats), min(lons), max(lats), max(lons))


def mbr_de_radio(lat: float, lon: float, radio_m: float) -> tuple:
    dlat = radio_m / METROS_POR_GRADO
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    dlon = radio_m / (METROS_POR_GRADO * cos_lat)
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def como_punto(valor) -> tuple:
    if hasattr(valor, "lat"):
        return (float(valor.lat), float(valor.lon))
    lat, lon = valor
    return (float(lat), float(lon))
