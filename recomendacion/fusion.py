"""Fusión ponderada por posiciones con explicaciones reproducibles."""
import math

MODALIDADES = ('visual', 'texto', 'metadata', 'compras')


def fusionar(listas, pesos, constante=60):
    if set(pesos) != set(MODALIDADES):
        raise ValueError('Se requieren pesos para visual, texto, metadata y compras')
    if any(not math.isfinite(v) or v < 0 for v in pesos.values()) or sum(pesos.values()) <= 0:
        raise ValueError('Los pesos deben ser finitos, no negativos y sumar más de cero')
    activas = [m for m in MODALIDADES if listas.get(m) and pesos[m] > 0]
    total = sum(pesos[m] for m in activas)
    productos = {}
    for modalidad in activas:
        vistos = set()
        posicion = 0
        for pid, original in listas[modalidad]:
            if pid in vistos:
                continue
            vistos.add(pid)
            posicion += 1
            aporte = pesos[modalidad] / total / (constante + posicion)
            p = productos.setdefault(pid, {'id': pid, 'score_total': 0.0, 'aportes': {},
                                          'posiciones': {}, 'scores_originales': {}})
            p['score_total'] += aporte
            p['aportes'][modalidad] = aporte
            p['posiciones'][modalidad] = posicion
            p['scores_originales'][modalidad] = float(original)
    for p in productos.values():
        p['aportes_pct'] = {m: 100 * p['aportes'].get(m, 0) / p['score_total'] for m in MODALIDADES}
    return sorted(productos.values(), key=lambda p: (-p['score_total'], p['id']))
