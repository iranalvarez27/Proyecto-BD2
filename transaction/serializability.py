from collections import deque


class ConflictGraph:
    def __init__(self):
        self._nodos: set = set()
        self._aristas: set = set()

    def agregar_conflicto(self, ti, tj) -> None:
        if ti == tj:
            return
        self._nodos.add(ti)
        self._nodos.add(tj)
        self._aristas.add((ti, tj))

    @property
    def nodos(self) -> set:
        return set(self._nodos)

    @property
    def aristas(self) -> set:
        return set(self._aristas)

    def _adyacencia(self) -> dict:
        adj: dict = {n: [] for n in self._nodos}
        for a, b in self._aristas:
            adj[a].append(b)
        return adj

    def encontrar_ciclo(self):
        adj = self._adyacencia()
        estado = {}  # 0=no visitado, 1=en pila, 2=cerrado

        def dfs(nodo, camino):
            estado[nodo] = 1
            camino.append(nodo)
            for vecino in adj.get(nodo, []):
                if estado.get(vecino) == 1:
                    idx = camino.index(vecino)
                    return camino[idx:] + [vecino]
                if estado.get(vecino) != 2:
                    resultado = dfs(vecino, camino)
                    if resultado is not None:
                        return resultado
            camino.pop()
            estado[nodo] = 2
            return None

        for nodo in sorted(self._nodos, key=str):
            if estado.get(nodo) is None:
                resultado = dfs(nodo, [])
                if resultado is not None:
                    return resultado
        return None

    def es_aciclico(self) -> bool:
        return self.encontrar_ciclo() is None

    def orden_serial(self):
        indeg = {n: 0 for n in self._nodos}
        adj = self._adyacencia()
        for a, b in self._aristas:
            indeg[b] += 1

        cola = deque(sorted((n for n in self._nodos if indeg[n] == 0), key=str))
        orden = []
        while cola:
            n = cola.popleft()
            orden.append(n)
            for m in sorted(adj.get(n, []), key=str):
                indeg[m] -= 1
                if indeg[m] == 0:
                    cola.append(m)

        if len(orden) != len(self._nodos):
            return None
        return orden


def construir_grafo_precedencia(historia) -> ConflictGraph:
    grafo = ConflictGraph()
    por_recurso: dict = {}

    for xact_id, recurso, modo, ts in sorted(historia, key=lambda e: e[3]):
        anteriores = por_recurso.setdefault(recurso, [])
        for otro_xact, otro_modo in anteriores:
            if otro_xact == xact_id:
                continue
            conflicto = not (modo == "S" and otro_modo == "S")
            if conflicto:
                grafo.agregar_conflicto(otro_xact, xact_id)
        anteriores.append((xact_id, modo))

    return grafo
