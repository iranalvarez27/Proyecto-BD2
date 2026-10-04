import random
from common.geo import point_in_polygon

# (distrito, latitud, longitud, peso relativo)
DISTRITOS = [
    ("Cercado de Lima", -12.0464, -77.0428, 1.4),
    ("Miraflores", -12.1211, -77.0297, 1.5),
    ("San Isidro", -12.0977, -77.0365, 1.3),
    ("Barranco", -12.1494, -77.0219, 0.8),
    ("Santiago de Surco", -12.1450, -76.9917, 1.3),
    ("La Molina", -12.0876, -76.9372, 0.9),
    ("San Miguel", -12.0773, -77.0907, 0.9),
    ("Los Olivos", -11.9920, -77.0708, 1.0),
    ("San Juan de Lurigancho", -11.9760, -77.0050, 1.2),
    ("Callao", -12.0566, -77.1181, 0.8),
    ("Ate", -12.0260, -76.9186, 0.9),
    ("Villa El Salvador", -12.2130, -76.9390, 0.8),
    ("San Borja", -12.1070, -76.9990, 0.9),
    ("Jesus Maria", -12.0750, -77.0480, 0.8),
    ("Pueblo Libre", -12.0760, -77.0640, 0.7),
    ("Lince", -12.0870, -77.0360, 0.7),
    ("Surquillo", -12.1130, -77.0140, 0.7),
    ("Chorrillos", -12.1760, -77.0150, 0.8),
    ("Comas", -11.9450, -77.0600, 0.9),
    ("San Martin de Porres", -12.0050, -77.0600, 1.0),
]

CATEGORIAS = ["Farmacia", "Restaurante", "Grifo", "Supermercado", "Cafeteria",
              "Libreria", "Ferreteria", "Banco", "Panaderia", "Bodega"]

# Referencia util para las consultas de ejemplo (campus UTEC, Barranco).
UTEC = (-12.1354, -77.0224)

DISPERSION_GRADOS = 0.012   # ~1.3 km de desviacion estandar
LIMA_BBOX = (-12.30, -77.20, -11.85, -76.80)  # lat_min, lon_min, lat_max, lon_max

# Polígono que delimita la tierra firme de Lima Metropolitana y Callao (excluyendo el Océano Pacífico).
# Vértices en formato (lon, lat) requeridos por point_in_polygon(x, y, vertices).
POLIGONO_TIERRA_LIMA = [
    (-77.1750, -11.750),  # Ancón norte
    (-77.1450, -11.870),  # Ventanilla
    (-77.1350, -12.010),  # Bocanegra / Callao norte
    (-77.1480, -12.055),  # Callao centro / Puerto
    (-77.1650, -12.070),  # La Punta (extremo oeste)
    (-77.1600, -12.074),  # La Punta sur
    (-77.1450, -12.068),  # Chucuito
    (-77.1150, -12.075),  # Costanera Callao / Bellavista
    (-77.0950, -12.085),  # San Miguel (Costanera)
    (-77.0720, -12.097),  # Magdalena del Mar
    (-77.0520, -12.108),  # San Isidro (Costa Verde)
    (-77.0405, -12.122),  # Miraflores (Faro de la Marina / Acantilado)
    (-77.0305, -12.133),  # Miraflores (Larcomar / Armendáriz)
    (-77.0235, -12.150),  # Barranco (Bajada de Baños)
    (-77.0260, -12.162),  # Chorrillos (Agua Dulce)
    (-77.0350, -12.176),  # Chorrillos (Morro Solar / La Herradura)
    (-77.0250, -12.205),  # La Chira
    (-76.9750, -12.235),  # Villa El Salvador (Litoral)
    (-76.9150, -12.280),  # Lurín costa
    (-76.8500, -12.350),  # Extremo sur litoral
    (-76.6000, -12.350),  # Límite este (tierra / sierra sur)
    (-76.6000, -11.750),  # Límite este (tierra / sierra norte)
]


def generar_tiendas(n: int, seed: int = 2026) -> list:
    rng = random.Random(seed + n)
    pesos = [d[3] for d in DISTRITOS]
    filas = []
    lat_min, lon_min, lat_max, lon_max = LIMA_BBOX
    for i in range(1, n + 1):
        distrito, lat0, lon0, _peso = rng.choices(DISTRITOS, weights=pesos, k=1)[0]
        while True:
            lat = min(lat_max, max(lat_min, rng.gauss(lat0, DISPERSION_GRADOS)))
            lon = min(lon_max, max(lon_min, rng.gauss(lon0, DISPERSION_GRADOS)))
            if point_in_polygon(lon, lat, POLIGONO_TIERRA_LIMA):
                break
        categoria = rng.choice(CATEGORIAS)
        nombre = f"{categoria} {distrito} {i}"[:40]
        filas.append((i, nombre, categoria, (round(lat, 6), round(lon, 6))))
    return filas


def centros_de_consulta(n: int, seed: int = 99) -> list:
    rng = random.Random(seed)
    centros = []
    lat_min, lon_min, lat_max, lon_max = LIMA_BBOX
    for _ in range(n):
        _d, lat0, lon0, _p = rng.choice(DISTRITOS)
        while True:
            lat = min(lat_max, max(lat_min, rng.gauss(lat0, DISPERSION_GRADOS)))
            lon = min(lon_max, max(lon_min, rng.gauss(lon0, DISPERSION_GRADOS)))
            if point_in_polygon(lon, lat, POLIGONO_TIERRA_LIMA):
                break
        centros.append((round(lat, 6), round(lon, 6)))
    return centros
