import math
from typing import NamedTuple

# x = longitud, y = latitud (como ST_MakePoint(x, y) de PostGIS)

EARTH_RADIUS_M = 6_371_000.0
METERS_PER_DEGREE = math.pi * EARTH_RADIUS_M / 180.0
EPS = 1e-12

HAVERSINE = "haversine"
EUCLIDEAN = "euclidean"


class MBR(NamedTuple):
    """MBR R = {L, U} con L = (x_min, y_min) y U = (x_max, y_max); un punto es un MBR degenerado."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @classmethod
    def of_point(cls, x: float, y: float) -> "MBR":
        return cls(x, y, x, y)

    @classmethod
    def of_points(cls, points) -> "MBR":
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return cls(min(xs), min(ys), max(xs), max(ys))

    def area(self) -> float:
        return (self.x_max - self.x_min) * (self.y_max - self.y_min)

    def union(self, other) -> "MBR":
        x_min, y_min, x_max, y_max = other
        return MBR(min(self.x_min, x_min), min(self.y_min, y_min),
                    max(self.x_max, x_max), max(self.y_max, y_max))

    def enlargement(self, other) -> float:
        return self.union(other).area() - self.area()

    def intersects(self, other) -> bool:
        x_min, y_min, x_max, y_max = other
        return (self.x_min <= x_max and x_min <= self.x_max
                and self.y_min <= y_max and y_min <= self.y_max)

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    def contains_rect(self, other) -> bool:
        x_min, y_min, x_max, y_max = other
        return (self.x_min <= x_min and x_max <= self.x_max
                and self.y_min <= y_min and y_max <= self.y_max)

    def mindist(self, other) -> float:
        x_min, y_min, x_max, y_max = other
        return math.hypot(_gap(self.x_min, self.x_max, x_min, x_max),
                          _gap(self.y_min, self.y_max, y_min, y_max))


def _gap(a_min: float, a_max: float, b_min: float, b_max: float) -> float:
    if a_max < b_min:
        return b_min - a_max
    if b_max < a_min:
        return a_min - b_max
    return 0.0



def haversine_m(x: float, y: float, rect) -> float:
    x_min, y_min, x_max, y_max = rect
    dx = _gap(x, x, x_min, x_max)
    if dx:
        # la caja puede estar mas cerca cruzando el antimeridiano
        dx = min(dx, 360.0 - abs(x - (x_max if x < x_min else x_min)))
    dy = _gap(y, y, y_min, y_max)
    if dx == 0.0 and dy == 0.0:
        return 0.0
    cos_min = min(math.cos(math.radians(y_min)), math.cos(math.radians(y_max)))
    a = (math.sin(math.radians(dy) / 2) ** 2
         + math.cos(math.radians(y)) * cos_min * math.sin(math.radians(dx) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def euclidean_m(x: float, y: float, rect) -> float:
    x_min, y_min, x_max, y_max = rect
    dx = _gap(x, x, x_min, x_max)
    dy = _gap(y, y, y_min, y_max)
    if dx == 0.0 and dy == 0.0:
        return 0.0
    cos_min = min(math.cos(math.radians((y + y_min) / 2)), math.cos(math.radians((y + y_max) / 2)))
    return math.hypot(dx * METERS_PER_DEGREE * cos_min, dy * METERS_PER_DEGREE)


def _cos_max(a: float, b: float) -> float:
    if a <= 0.0 <= b:
        return 1.0
    return max(math.cos(math.radians(a)), math.cos(math.radians(b)))


# cotas superiores: ningun punto de rect esta a mas de esta distancia de (x, y)
def haversine_max_m(x: float, y: float, rect) -> float:
    x_min, y_min, x_max, y_max = rect
    dx = min(180.0, max(abs(x - x_min), abs(x - x_max)))
    dy = max(abs(y - y_min), abs(y - y_max))
    a = (math.sin(math.radians(dy) / 2) ** 2
         + math.cos(math.radians(y)) * _cos_max(y_min, y_max) * math.sin(math.radians(dx) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def euclidean_max_m(x: float, y: float, rect) -> float:
    x_min, y_min, x_max, y_max = rect
    dx = max(abs(x - x_min), abs(x - x_max))
    dy = max(abs(y - y_min), abs(y - y_max))
    cos_max = _cos_max((y + y_min) / 2, (y + y_max) / 2)
    return math.hypot(dx * METERS_PER_DEGREE * cos_max, dy * METERS_PER_DEGREE)


METRICS = {HAVERSINE: haversine_m, EUCLIDEAN: euclidean_m}
MAX_METRICS = {HAVERSINE: haversine_max_m, EUCLIDEAN: euclidean_max_m}


def get_metric(name: str):
    try:
        return METRICS[name]
    except KeyError:
        raise ValueError(f"metrica desconocida '{name}' (validas: {', '.join(METRICS)})")


def get_max_metric(name: str):
    get_metric(name)
    return MAX_METRICS[name]



def _orientation(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def point_in_polygon(x: float, y: float, vertices: list) -> bool:
    n = len(vertices)
    if n < 3:
        return False
    for i in range(n):
        ax, ay = vertices[i]
        bx, by = vertices[(i + 1) % n]
        if (abs(_orientation(ax, ay, bx, by, x, y)) <= EPS
                and min(ax, bx) - EPS <= x <= max(ax, bx) + EPS
                and min(ay, by) - EPS <= y <= max(ay, by) + EPS):
            return True
    inside = False
    for i in range(n):
        ax, ay = vertices[i]
        bx, by = vertices[(i + 1) % n]
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def _segments_meet(ax: float, ay: float, bx: float, by: float,
                   cx: float, cy: float, dx: float, dy: float) -> bool:
    # ante la duda (colineales, tocandose) dice que si
    d1 = _orientation(cx, cy, dx, dy, ax, ay)
    d2 = _orientation(cx, cy, dx, dy, bx, by)
    if (d1 > EPS and d2 > EPS) or (d1 < -EPS and d2 < -EPS):
        return False
    d3 = _orientation(ax, ay, bx, by, cx, cy)
    d4 = _orientation(ax, ay, bx, by, dx, dy)
    return not ((d3 > EPS and d4 > EPS) or (d3 < -EPS and d4 < -EPS))


def rect_in_polygon(rect, vertices: list) -> bool:
    x_min, y_min, x_max, y_max = rect
    corners = [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]
    if not all(point_in_polygon(x, y, vertices) for x, y in corners):
        return False
    n = len(vertices)
    for i in range(n):
        ax, ay = vertices[i]
        bx, by = vertices[(i + 1) % n]
        for j in range(4):
            (cx, cy), (dx, dy) = corners[j], corners[(j + 1) % 4]
            if _segments_meet(ax, ay, bx, by, cx, cy, dx, dy):
                return False
    return True
