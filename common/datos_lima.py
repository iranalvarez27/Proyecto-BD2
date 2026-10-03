import random

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


def generar_tiendas(n: int, seed: int = 2026) -> list:
    rng = random.Random(seed + n)
    pesos = [d[3] for d in DISTRITOS]
    filas = []
    lat_min, lon_min, lat_max, lon_max = LIMA_BBOX
    for i in range(1, n + 1):
        distrito, lat0, lon0, _peso = rng.choices(DISTRITOS, weights=pesos, k=1)[0]
        lat = min(lat_max, max(lat_min, rng.gauss(lat0, DISPERSION_GRADOS)))
        lon = min(lon_max, max(lon_min, rng.gauss(lon0, DISPERSION_GRADOS)))
        categoria = rng.choice(CATEGORIAS)
        nombre = f"{categoria} {distrito} {i}"[:40]
        filas.append((i, nombre, categoria, (round(lat, 6), round(lon, 6))))
    return filas


def centros_de_consulta(n: int, seed: int = 99) -> list:
    rng = random.Random(seed)
    centros = []
    for _ in range(n):
        _d, lat0, lon0, _p = rng.choice(DISTRITOS)
        centros.append((rng.gauss(lat0, DISPERSION_GRADOS), rng.gauss(lon0, DISPERSION_GRADOS)))
    return centros
