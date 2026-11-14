"""Afinidad item-item (coseno entre compradores, con shrinkage) a partir de compras reales y de la demo."""
from collections import Counter, defaultdict
import csv
from itertools import combinations
import math

from recomendacion.repositorio import literal

MAX_VECINOS = 30
# los usuarios con muchisimas compras no aportan co-compras informativas y disparan los pares
MAX_POR_USUARIO = 50
# shrinkage de Koren (KDD 2008): con LAMBDA usuarios en comun el par conserva la mitad del coseno
LAMBDA = 10


def clave(a, b):
    return a * 2147483647 + b


def coseno(soporte, compradores_a, compradores_b):
    return soporte / math.sqrt(compradores_a * compradores_b)


def puntaje(soporte, compradores_a, compradores_b, lam=LAMBDA):
    return coseno(soporte, compradores_a, compradores_b) * soporte / (soporte + lam)


def contar(compras_por_usuario, max_por_usuario=MAX_POR_USUARIO):
    """Compradores distintos por producto y usuarios en comun por par de productos."""
    compradores, soportes = Counter(), Counter()
    for productos in compras_por_usuario:
        compradores.update(productos)
        if len(productos) <= max_por_usuario:
            soportes.update(combinations(sorted(productos), 2))
    return compradores, soportes


def vecinos(compradores, soportes, max_vecinos=MAX_VECINOS):
    """Los max_vecinos mas afines de cada producto, como (origen, destino, score, soporte)."""
    por_producto = defaultdict(list)
    for (a, b), soporte in soportes.items():
        score = puntaje(soporte, compradores[a], compradores[b])
        por_producto[a].append((b, score, soporte))
        por_producto[b].append((a, score, soporte))
    return [(a, b, score, soporte) for a in sorted(por_producto)
            for b, score, soporte in sorted(por_producto[a], key=lambda v: (-v[1], -v[2], v[0]))[:max_vecinos]]


def leer_compras(ruta_csv, solo_verificadas=True):
    usuarios = defaultdict(set)
    with open(ruta_csv, encoding='utf-8', newline='') as f:
        for fila in csv.DictReader(f):
            if not solo_verificadas or fila['compra_verificada'] == 'True':
                usuarios[fila['usuario_id']].add(int(fila['producto_id']))
    return list(usuarios.values())


def calcular_afinidades(interacciones, max_vecinos=MAX_VECINOS):
    usuarios = defaultdict(set)
    for fila in interacciones:
        if fila['tipo'] == 'compra':
            usuarios[fila['usuario_id']].add(fila['producto_id'])
    return vecinos(*contar(usuarios.values()), max_vecinos)


def cargar_base(repo, compras_por_usuario, max_vecinos=MAX_VECINOS):
    """Carga las afinidades precalculadas y los compradores por producto (tablas vacias)."""
    compradores, soportes = contar(compras_por_usuario)
    for pid, n in sorted(compradores.items()):
        repo.insertar('ecommerce_compradores', [pid, n])
    filas = vecinos(compradores, soportes, max_vecinos)
    for a, b, score, soporte in filas:
        repo.insertar('ecommerce_afinidades', [clave(a, b), a, b, score, soporte])
    return len(filas)


def _compradores(repo, pid):
    fila = repo.ejecutar(f'SELECT compradores FROM ecommerce_compradores WHERE id = {int(pid)}')
    return fila[0]['compradores'] if fila else 0


def _soporte(repo, a, b):
    for x, y in ((a, b), (b, a)):
        fila = repo.ejecutar(f'SELECT soporte FROM ecommerce_afinidades WHERE id = {clave(x, y)}')
        if fila:
            return fila[0]['soporte']
    return 0


def _guardar(repo, a, b, score, soporte):
    if repo.ejecutar(f'SELECT id FROM ecommerce_afinidades WHERE id = {clave(a, b)}'):
        repo.ejecutar(f'UPDATE ecommerce_afinidades SET score = {literal(score)}, soporte = {soporte} WHERE id = {clave(a, b)}')
    else:
        repo.insertar('ecommerce_afinidades', [clave(a, b), a, b, score, soporte])


def registrar_compra(repo, previos, nuevos):
    """Suma una compra de la demo sobre la base: actualiza compradores, pares y scores afectados.

    previos son los productos que el usuario ya habia comprado; los scores de las listas
    de otros productos que apuntan a estos quedan con el denominador anterior hasta
    recalcular la base.
    """
    nuevos = set(nuevos) - set(previos)
    if not nuevos:
        return set()
    for pid in sorted(nuevos):
        n = _compradores(repo, pid)
        if n:
            repo.ejecutar(f'UPDATE ecommerce_compradores SET compradores = {n + 1} WHERE id = {pid}')
        else:
            repo.insertar('ecommerce_compradores', [pid, 1])
    pares = {tuple(sorted((a, b))) for a in nuevos for b in set(previos) | nuevos if a != b}
    for a, b in sorted(pares):
        soporte = _soporte(repo, a, b) + 1
        score = puntaje(soporte, _compradores(repo, a), _compradores(repo, b))
        _guardar(repo, a, b, score, soporte)
        _guardar(repo, b, a, score, soporte)
    # el denominador de los productos comprados cambio: se recalculan sus listas
    tocados = {p for par in pares for p in par}
    for pid in sorted(nuevos):
        for fila in repo.ejecutar(f'SELECT * FROM ecommerce_afinidades WHERE producto_origen = {pid}'):
            if tuple(sorted((pid, fila['producto_destino']))) in pares:
                continue
            score = puntaje(fila['soporte'], _compradores(repo, pid), _compradores(repo, fila['producto_destino']))
            repo.ejecutar(f'UPDATE ecommerce_afinidades SET score = {literal(score)} WHERE id = {fila["id"]}')
    return tocados
