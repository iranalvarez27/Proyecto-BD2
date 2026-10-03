import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _here in sys.path:
    sys.path.remove(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from common.geo import (
    MBR,
    Point,
    caja_alrededor,
    distancia,
    euclidiana,
    euclidiana_aprox_m,
    haversine_m,
    knn_secuencial,
    mbr_de_puntos,
    mindist,
    poligonos_intersectan,
    punto_en_poligono,
    puntos_en_poligono,
    range_mbr_secuencial,
    range_query_secuencial,
    segmentos_intersectan,
)

LIMA = Point(-77.0428, -12.0464)
PUCP = Point(-77.0803, -12.0694)
KENNEDY = Point(-77.0297, -12.1211)
CALLAO_PUNTO = Point(-77.1181, -12.0566)

MIRAFLORES = [
    (-77.045, -12.105),
    (-77.020, -12.105),
    (-77.020, -12.140),
    (-77.045, -12.140),
]
SAN_ISIDRO = [
    (-77.050, -12.090),
    (-77.025, -12.090),
    (-77.025, -12.110),
    (-77.050, -12.110),
]
CALLAO = [
    (-77.140, -12.010),
    (-77.100, -12.010),
    (-77.100, -12.050),
    (-77.140, -12.050),
]
PUNTOS = [LIMA, PUCP, KENNEDY, CALLAO_PUNTO]


def check(ok, msg):
    estado = "OK" if ok else "FAIL"
    print(f"  [{estado}] {msg}")
    if not ok:
        raise SystemExit(1)


print("\n=== Haversine / Euclidiana ===")
d_hav = haversine_m(LIMA.x, LIMA.y, PUCP.x, PUCP.y)
d_plana = euclidiana_aprox_m(LIMA.x, LIMA.y, PUCP.x, PUCP.y)
d_xy = euclidiana(LIMA, PUCP)
print(f"  Lima-PUCP haversine      = {d_hav:.1f} m")
print(f"  Lima-PUCP euclidiana_m   = {d_plana:.1f} m")
print(f"  Lima-PUCP euclidiana xy  = {d_xy:.6f} deg")
check(4000 < d_hav < 7000, "Haversine Lima-PUCP en rango 4-7 km")
check(abs(d_hav - d_plana) / d_hav < 0.05, "Euclidiana en metros aproxima Haversine (<5%)")
check(distancia(LIMA, PUCP, "haversine") == d_hav, "distancia() usa Haversine")
check(distancia(LIMA, PUCP, "euclidiana") == d_xy, "distancia(euclidiana) usa xy")
check(distancia(LIMA, PUCP, "euclidiana_m") == d_plana, "distancia(euclidiana_m) usa metros")

print("\n=== Punto en poligono ===")
check(punto_en_poligono(KENNEDY.x, KENNEDY.y, MIRAFLORES), "Kennedy dentro de Miraflores")
check(not punto_en_poligono(LIMA.x, LIMA.y, MIRAFLORES), "Plaza San Martin fuera de Miraflores")
check(not punto_en_poligono(LIMA.x, LIMA.y, []), "poligono vacio => fuera")
borde = Point(-77.045, -12.120)
check(punto_en_poligono(borde.x, borde.y, MIRAFLORES, include_boundary=True), "borde incluido")
check(not punto_en_poligono(borde.x, borde.y, MIRAFLORES, include_boundary=False), "borde excluido")
en_mira = puntos_en_poligono(PUNTOS, MIRAFLORES)
check(KENNEDY in en_mira and LIMA not in en_mira, "puntos_en_poligono filtra distrito")

print("\n=== Interseccion de segmentos / poligonos ===")
check(
    segmentos_intersectan((-77.04, -12.10), (-77.04, -12.13), (-77.05, -12.12), (-77.03, -12.12)),
    "cruz + se intersecta",
)
check(
    not segmentos_intersectan((-77.04, -12.10), (-77.04, -12.11), (-77.04, -12.13), (-77.04, -12.14)),
    "segmentos colineales separados no se tocan",
)
check(poligonos_intersectan(MIRAFLORES, SAN_ISIDRO), "Miraflores intersecta San Isidro")
check(not poligonos_intersectan(MIRAFLORES, CALLAO), "Miraflores no intersecta Callao")

print("\n=== MBR ===")
caja = caja_alrededor(LIMA.x, LIMA.y, 5000)
degen = MBR.from_point(LIMA)
check(isinstance(caja, MBR), "caja_alrededor devuelve MBR")
check(caja.contains_point(LIMA), "Lima dentro de su caja de 5 km")
check(caja.contains_mbr(degen), "caja contiene MBR degenerado de Lima")
check(caja.intersects(mbr_de_puntos([PUCP])), "PUCP cae en caja de 5 km alrededor de Lima")
check(not mbr_de_puntos(MIRAFLORES).intersects(mbr_de_puntos(CALLAO)), "MBR Miraflores vs Callao disjuntos")
check(caja.area() > 0, "area() del MBR es positiva")
check(degen.area() == 0.0, "MBR de un punto tiene area 0")
check(degen.mindist(LIMA) == 0.0, "MINDIST de un punto a su MBR es 0")
check(mindist(LIMA, caja) == 0.0, "mindist() wrapper")
check(caja.enlargement(degen) == 0.0, "enlargement de un punto interno es 0")
unido = mbr_de_puntos(MIRAFLORES).union(mbr_de_puntos(CALLAO))
check(unido.contains_mbr(mbr_de_puntos(MIRAFLORES)), "union contiene ambos MBR")

print("\n=== Range / k-NN secuencial ===")
r5 = range_query_secuencial(PUNTOS, LIMA, 5000)
check(LIMA in r5 and PUCP in r5, "range 5 km incluye Lima y PUCP")
check(KENNEDY not in r5, "range 5 km no incluye Kennedy")
en_caja = range_mbr_secuencial(PUNTOS, caja)
check(set(en_caja) == set(r5) or LIMA in en_caja, "range por MBR es prefiltro")
vecinos = knn_secuencial(PUNTOS, LIMA, k=2)
check(vecinos[0][0] == LIMA and vecinos[0][1] == 0.0, "k-NN k=2: el mas cercano es Lima")
check(vecinos[1][0] == PUCP, "k-NN k=2: segundo es PUCP")
check(knn_secuencial(PUNTOS, LIMA, k=0) == [], "k-NN k=0 vacio")

print("\ngeo.py OK")
