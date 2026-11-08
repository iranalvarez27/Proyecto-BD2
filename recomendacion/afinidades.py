"""Afinidad item-item calculada exclusivamente con eventos de compra."""
from collections import defaultdict, Counter
from itertools import combinations
import math


def calcular_afinidades(interacciones, max_vecinos=100):
    usuarios = defaultdict(set)
    compradores = defaultdict(set)
    for fila in interacciones:
        if fila['tipo'] == 'compra':
            usuarios[fila['usuario_id']].add(fila['producto_id'])
            compradores[fila['producto_id']].add(fila['usuario_id'])
    soportes = Counter()
    for productos in usuarios.values():
        soportes.update(combinations(sorted(productos), 2))
    vecinos = defaultdict(list)
    for (a, b), soporte in soportes.items():
        score = soporte / math.sqrt(len(compradores[a]) * len(compradores[b]))
        vecinos[a].append((b, score, soporte))
        vecinos[b].append((a, score, soporte))
    return [(a, b, score, soporte) for a in sorted(vecinos)
            for b, score, soporte in sorted(vecinos[a], key=lambda v: (-v[1], -v[2], v[0]))[:max_vecinos]]


def refrescar(repo):
    eventos = repo.ejecutar('SELECT * FROM ecommerce_interacciones')
    existentes = {r['id']: r for r in repo.ejecutar('SELECT * FROM ecommerce_afinidades')}
    nuevos = {a * 2147483647 + b: (a, b, score, soporte)
              for a, b, score, soporte in calcular_afinidades(eventos)}
    for identificador in existentes.keys() - nuevos.keys():
        repo.ejecutar(f'DELETE FROM ecommerce_afinidades WHERE id = {identificador}')
    for identificador, (a, b, score, soporte) in nuevos.items():
        viejo = existentes.get(identificador)
        if viejo is None:
            repo.insertar('ecommerce_afinidades', [identificador, a, b, score, soporte])
        elif viejo['score'] != score or viejo['soporte'] != soporte:
            repo.ejecutar(f'UPDATE ecommerce_afinidades SET score = {score}, soporte = {soporte} WHERE id = {identificador}')
    version = max((e['id'] for e in eventos if e['tipo'] == 'compra'), default=0)
    repo.ejecutar(f'UPDATE ecommerce_estado SET revision = {version} WHERE id = 1')
    return version
