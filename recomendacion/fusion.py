"""Combinacion convexa de scores normalizados (Bruch, Gai e Ingber), con aportes explicables.

Cada senal se lleva a [0, 1] antes de ponderar. Por defecto con min-max dentro de su lista;
una senal con escala global (compras) se divide por esa escala y se recorta a 1, asi conserva
su confianza absoluta: un par con mucha evidencia pesa mas que uno casual aunque ambos
encabecen su lista.
"""
import math

MODALIDADES = ('visual', 'texto', 'metadata', 'compras')


def normalizar(scores: list, escala: float | None = None) -> list:
    if escala is not None:
        return [min(1.0, max(0.0, s / escala)) for s in scores]
    minimo, maximo = min(scores), max(scores)
    if maximo == minimo:
        return [1.0] * len(scores)
    return [(s - minimo) / (maximo - minimo) for s in scores]


def fusionar(listas, pesos, escalas=None):
    if set(pesos) != set(MODALIDADES):
        raise ValueError('Se requieren pesos para visual, texto, metadata y compras')
    if any(not math.isfinite(v) or v < 0 for v in pesos.values()) or sum(pesos.values()) <= 0:
        raise ValueError('Los pesos deben ser finitos, no negativos y sumar más de cero')
    escalas = escalas or {}
    activas = [m for m in MODALIDADES if listas.get(m) and pesos[m] > 0]
    # los pesos de las senales sin candidatos se reparten entre las activas: siguen sumando 1
    total = sum(pesos[m] for m in activas)
    productos = {}
    for modalidad in activas:
        unicos, vistos = [], set()
        for pid, original in listas[modalidad]:
            if pid not in vistos:
                vistos.add(pid)
                unicos.append((pid, float(original)))
        normalizados = normalizar([s for _, s in unicos], escalas.get(modalidad))
        for posicion, ((pid, original), valor) in enumerate(zip(unicos, normalizados), 1):
            aporte = pesos[modalidad] / total * valor
            p = productos.setdefault(pid, {'id': pid, 'score_total': 0.0, 'aportes': {}, 'posiciones': {},
                                           'scores_originales': {}, 'scores_normalizados': {}})
            p['score_total'] += aporte
            p['aportes'][modalidad] = aporte
            p['posiciones'][modalidad] = posicion
            p['scores_originales'][modalidad] = original
            p['scores_normalizados'][modalidad] = valor
    for p in productos.values():
        p['aportes_pct'] = {m: 100 * p['aportes'].get(m, 0) / p['score_total'] if p['score_total'] else 0.0
                            for m in MODALIDADES}
    return sorted(productos.values(), key=lambda p: (-p['score_total'], p['id']))
