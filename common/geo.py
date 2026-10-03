import math
import heapq
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0
METROS_POR_GRADO = 111_320.0
EPS = 1e-12

# Constantes de métrica usadas por index/rtree.py y query/conexion.py
METRICA_HAVERSINE = "haversine"
METRICA_EUCLIDIANA = "euclidiana"


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    @property
    def lon(self) -> float:
        return self.x

    @property
    def lat(self) -> float:
        return self.y

    def as_tuple(self) -> tuple[float, float]:
        return (float(self.x), float(self.y))


@dataclass(frozen=True)
class MBR:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        if self.min_x > self.max_x:
            raise ValueError("min_x no puede ser mayor que max_x")
        if self.min_y > self.max_y:
            raise ValueError("min_y no puede ser mayor que max_y")

    @classmethod
    def from_point(cls, point: Point) -> "MBR":
        return cls(
            min_x=point.x,
            min_y=point.y,
            max_x=point.x,
            max_y=point.y,
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.min_x, self.min_y, self.max_x, self.max_y)

    def width(self) -> float:
        return self.max_x - self.min_x

    def height(self) -> float:
        return self.max_y - self.min_y

    def area(self) -> float:
        return self.width() * self.height()

    def intersects(self, other: "MBR") -> bool:
        return not (
            self.max_x < other.min_x
            or self.min_x > other.max_x
            or self.max_y < other.min_y
            or self.min_y > other.max_y
        )

    def contains_point(self, point: Point) -> bool:
        return (
            self.min_x <= point.x <= self.max_x
            and self.min_y <= point.y <= self.max_y
        )

    def contains_mbr(self, other: "MBR") -> bool:
        return (
            self.min_x <= other.min_x
            and self.min_y <= other.min_y
            and self.max_x >= other.max_x
            and self.max_y >= other.max_y
        )

    def union(self, other: "MBR") -> "MBR":
        return MBR(
            min_x=min(self.min_x, other.min_x),
            min_y=min(self.min_y, other.min_y),
            max_x=max(self.max_x, other.max_x),
            max_y=max(self.max_y, other.max_y),
        )

    def enlargement(self, other: "MBR") -> float:
        expanded = self.union(other)
        return expanded.area() - self.area()

    def mindist(self, point: Point) -> float:
        if point.x < self.min_x:
            dx = self.min_x - point.x
        elif point.x > self.max_x:
            dx = point.x - self.max_x
        else:
            dx = 0.0

        if point.y < self.min_y:
            dy = self.min_y - point.y
        elif point.y > self.max_y:
            dy = point.y - self.max_y
        else:
            dy = 0.0

        return math.hypot(dx, dy)


def as_point(valor) -> Point:
    if isinstance(valor, Point):
        return valor
    if hasattr(valor, "x") and hasattr(valor, "y"):
        return Point(float(valor.x), float(valor.y))
    if hasattr(valor, "lat") and hasattr(valor, "lon"):
        return Point(float(valor.lon), float(valor.lat))
    x, y = valor
    return Point(float(x), float(y))


def euclidiana(a, b) -> float:
    p1 = as_point(a)
    p2 = as_point(b)
    return math.hypot(p2.x - p1.x, p2.y - p1.y)


def euclidiana_aprox_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat_media = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * METROS_POR_GRADO * math.cos(math.radians(lat_media))
    dy = (lat2 - lat1) * METROS_POR_GRADO
    return math.hypot(dx, dy)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if not (-90.0 <= lat1 <= 90.0 and -90.0 <= lat2 <= 90.0):
        raise ValueError("La latitud debe estar entre -90 y 90 grados")
    if not (-180.0 <= lon1 <= 180.0 and -180.0 <= lon2 <= 180.0):
        raise ValueError("La longitud debe estar entre -180 y 180 grados")

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    a = max(0.0, min(1.0, a))
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def distancia(a, b, metric: str = "haversine") -> float:
    p1 = as_point(a)
    p2 = as_point(b)
    metric = metric.lower()
    if metric in ("haversine", "geo", "geodesica", "geodésica"):
        return haversine_m(p1.y, p1.x, p2.y, p2.x)  # lat=y, lon=x
    if metric in ("euclidiana", "euclidean"):
        return euclidiana(p1, p2)
    if metric in ("euclidiana_m", "euclidean_m", "plana_m"):
        return euclidiana_aprox_m(p1.y, p1.x, p2.y, p2.x)  # lat=y, lon=x
    raise ValueError(f"Métrica espacial desconocida: '{metric}'")


def mindist(query, mbr: MBR) -> float:
    return mbr.mindist(as_point(query))


def _orientacion(a: Point, b: Point, c: Point) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _en_segmento(a: Point, b: Point, c: Point) -> bool:
    return (
        min(a.x, b.x) - EPS <= c.x <= max(a.x, b.x) + EPS
        and min(a.y, b.y) - EPS <= c.y <= max(a.y, b.y) + EPS
    )


def segmentos_intersectan(a1, a2, b1, b2) -> bool:
    p1 = as_point(a1)
    p2 = as_point(a2)
    q1 = as_point(b1)
    q2 = as_point(b2)

    o1 = _orientacion(p1, p2, q1)
    o2 = _orientacion(p1, p2, q2)
    o3 = _orientacion(q1, q2, p1)
    o4 = _orientacion(q1, q2, p2)

    if (
        (o1 > EPS and o2 < -EPS or o1 < -EPS and o2 > EPS)
        and (o3 > EPS and o4 < -EPS or o3 < -EPS and o4 > EPS)
    ):
        return True
    if abs(o1) <= EPS and _en_segmento(p1, p2, q1):
        return True
    if abs(o2) <= EPS and _en_segmento(p1, p2, q2):
        return True
    if abs(o3) <= EPS and _en_segmento(q1, q2, p1):
        return True
    if abs(o4) <= EPS and _en_segmento(q1, q2, p2):
        return True
    return False


def punto_en_poligono(x: float, y: float, vertices: list, include_boundary: bool = True) -> bool:
    punto = Point(float(x), float(y))
    verts = [as_point(v) for v in vertices]
    if len(verts) < 3:
        return False

    for i in range(len(verts)):
        a = verts[i]
        b = verts[(i + 1) % len(verts)]
        if abs(_orientacion(a, b, punto)) <= EPS and _en_segmento(a, b, punto):
            return include_boundary

    dentro = False
    n = len(verts)
    for i in range(n):
        a = verts[i]
        b = verts[(i + 1) % n]
        if (a.y > punto.y) != (b.y > punto.y):
            x_interseccion = a.x + (punto.y - a.y) * (b.x - a.x) / (b.y - a.y)
            if punto.x < x_interseccion:
                dentro = not dentro
    return dentro


def poligonos_intersectan(poly_a: list, poly_b: list) -> bool:
    a = [as_point(v) for v in poly_a]
    b = [as_point(v) for v in poly_b]
    if len(a) < 3 or len(b) < 3:
        return False
    if punto_en_poligono(a[0].x, a[0].y, b):
        return True
    if punto_en_poligono(b[0].x, b[0].y, a):
        return True
    na = len(a)
    nb = len(b)
    for i in range(na):
        a1 = a[i]
        a2 = a[(i + 1) % na]
        for j in range(nb):
            b1 = b[j]
            b2 = b[(j + 1) % nb]
            if segmentos_intersectan(a1, a2, b1, b2):
                return True
    return False


def mbr_de_puntos(vertices: list) -> MBR:
    pts = [as_point(v) for v in vertices]
    if not pts:
        raise ValueError("mbr_de_puntos necesita al menos un punto")
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    return MBR(
        min_x=min(xs),
        min_y=min(ys),
        max_x=max(xs),
        max_y=max(ys),
    )


def caja_alrededor(x: float, y: float, radio_m: float) -> MBR:
    if radio_m < 0:
        raise ValueError("El radio no puede ser negativo")
    if not (-90.0 <= y <= 90.0):
        raise ValueError("Latitud inválida")
    if not (-180.0 <= x <= 180.0):
        raise ValueError("Longitud inválida")

    dy = radio_m / METROS_POR_GRADO
    cos_lat = math.cos(math.radians(y))
    if abs(cos_lat) <= EPS:
        dx = 180.0
    else:
        dx = radio_m / (METROS_POR_GRADO * abs(cos_lat))
        dx = min(dx, 180.0)

    return MBR(
        min_x=x - dx,
        min_y=max(-90.0, y - dy),
        max_x=x + dx,
        max_y=min(90.0, y + dy),
    )


def range_query_secuencial(puntos, query, radio: float, metric: str = "haversine") -> list[Point]:
    if radio < 0:
        raise ValueError("El radio no puede ser negativo")
    q = as_point(query)
    resultado = []
    for valor in puntos:
        p = as_point(valor)
        d = distancia(q, p, metric)
        if d <= radio:
            resultado.append(p)
    return resultado


def range_mbr_secuencial(puntos, query_mbr: MBR) -> list[Point]:
    resultado = []
    for valor in puntos:
        p = as_point(valor)
        if query_mbr.contains_point(p):
            resultado.append(p)
    return resultado


def puntos_en_poligono(puntos, vertices) -> list[Point]:
    resultado = []
    for valor in puntos:
        p = as_point(valor)
        if punto_en_poligono(p.x, p.y, vertices):
            resultado.append(p)
    return resultado


def knn_secuencial(puntos, query, k: int, metric: str = "haversine") -> list[tuple[Point, float]]:
    if k <= 0:
        return []
    q = as_point(query)
    mejores = []
    contador = 0
    for valor in puntos:
        p = as_point(valor)
        d = distancia(q, p, metric)
        item = (-d, contador, p)
        contador += 1
        if len(mejores) < k:
            heapq.heappush(mejores, item)
        else:
            peor_distancia = -mejores[0][0]
            if d < peor_distancia:
                heapq.heapreplace(mejores, item)
    resultado = [(p, -neg_d) for (neg_d, _, p) in mejores]
    resultado.sort(key=lambda item: item[1])
    return resultado


def como_punto(valor) -> tuple:
    if isinstance(valor, Point):
        # Point almacena x=lon, y=lat en notación cartesiana
        return (float(valor.y), float(valor.x))
    if hasattr(valor, "lat") and hasattr(valor, "lon"):
        return (float(valor.lat), float(valor.lon))
    if hasattr(valor, "x") and hasattr(valor, "y"):
        return (float(valor.y), float(valor.x))
    lat, lon = valor
    return (float(lat), float(lon))


# Alias que query/conexion.py importa como: euclidiana_m as _euclidiana_aprox_m
def euclidiana_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * METROS_POR_GRADO * math.cos(math.radians((lat1 + lat2) / 2))
    dy = (lat2 - lat1) * METROS_POR_GRADO
    return math.sqrt(dx * dx + dy * dy)


def _separacion(valor: float, bajo: float, alto: float) -> float:
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


# Tabla de métricas: nombre -> (dist_punto_punto, mindist_punto_mbr)
_METRICAS = {
    METRICA_HAVERSINE: (haversine_m, mindist_haversine_m),
    METRICA_EUCLIDIANA: (euclidiana_m, mindist_euclidiana_m),
}


def resolver_metrica(metrica: str):
    try:
        return _METRICAS[metrica]
    except KeyError:
        raise ValueError(f"metrica desconocida '{metrica}' (validas: {', '.join(_METRICAS)})")


def mbr_de_poligono(vertices: list) -> tuple:
    lats = [v[0] for v in vertices]
    lons = [v[1] for v in vertices]
    return (min(lats), min(lons), max(lats), max(lons))

