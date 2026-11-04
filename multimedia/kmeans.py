import numpy as np
from index.vector.metricas import euclidiana
from .config import KMEANS_BLOQUE, KMEANS_MAX_ITER, KMEANS_TOL, SEMILLA

def kmeans_pp(X: np.ndarray, K: int, rng: np.random.Generator) -> np.ndarray:
    n = len(X)
    if K <= 0:
        raise ValueError("K debe ser positivo")
    if K > n:
        raise ValueError(f"K={K} no puede superar el numero de puntos ({n})")

    centros = np.empty((K, X.shape[1]), dtype=np.float32)
    elegidos = np.zeros(n, dtype=bool)

    primero = int(rng.integers(n))
    centros[0] = X[primero]
    elegidos[primero] = True

    # Distancia cuadrada minima de cada punto al conjunto de centros elegido.
    d2 = np.full(n, np.inf, dtype=np.float64)

    for j in range(1, K):
        distancia = euclidiana(X, centros[j - 1:j])[:, 0].astype(np.float64)
        np.minimum(d2, distancia * distancia, out=d2)
        d2[elegidos] = 0.0
        total = d2.sum()
        if total <= 0 or not np.isfinite(total):
            # Todos los puntos restantes coinciden con un centro: tomar uno
            # cualquiera que no se haya usado.
            restantes = np.flatnonzero(~elegidos)
            if len(restantes) == 0:
                raise ValueError("no quedan puntos distintos para inicializar K centroides")
            idx = int(rng.choice(restantes))
        else:
            idx = int(rng.choice(n, p=d2 / total))
        centros[j] = X[idx]
        elegidos[idx] = True

    return centros


def asignar(X: np.ndarray, C: np.ndarray,
            bloque: int = KMEANS_BLOQUE) -> tuple[np.ndarray, np.ndarray]:

    X = np.asarray(X, dtype=np.float32)
    C = np.asarray(C, dtype=np.float32)
    n = len(X)
    etiquetas = np.empty(n, dtype=np.int64)
    distancias = np.empty(n, dtype=np.float32)

    for inicio in range(0, n, bloque):
        fin = min(inicio + bloque, n)
        d = euclidiana(X[inicio:fin], C)          # (bloque, K)
        idx = d.argmin(axis=1)
        etiquetas[inicio:fin] = idx
        distancias[inicio:fin] = d[np.arange(len(idx)), idx]

    return etiquetas, distancias


def recalcular(X: np.ndarray, etiquetas: np.ndarray, K: int,
               C: np.ndarray | None = None) -> np.ndarray:

    X = np.asarray(X, dtype=np.float32)
    n, d = X.shape
    conteos = np.bincount(etiquetas, minlength=K)
    C_nuevo = np.zeros((K, d), dtype=np.float32)
    if C is not None:
        C_nuevo[:] = np.asarray(C, dtype=np.float32)

    for j in range(d):
        sumas = np.bincount(etiquetas, weights=X[:, j], minlength=K)
        no_vacios = conteos > 0
        C_nuevo[no_vacios, j] = sumas[no_vacios] / conteos[no_vacios]

    return C_nuevo


def reubicar_vacios(C: np.ndarray, X: np.ndarray, etiquetas: np.ndarray,
                    distancias: np.ndarray) -> np.ndarray:

    K = len(C)
    vacios = np.flatnonzero(np.bincount(etiquetas, minlength=K) == 0)
    if len(vacios) == 0:
        return C

    C = np.array(C, dtype=np.float32, copy=True)
    d = np.array(distancias, dtype=np.float64, copy=True)
    for j in vacios:
        idx = int(np.argmax(d))
        C[j] = X[idx]
        d[idx] = -np.inf       # un punto no puede reubicar dos grupos
    return C


def inercia(X: np.ndarray, C: np.ndarray,
            bloque: int = KMEANS_BLOQUE) -> float:
    _, d = asignar(X, C, bloque)
    return float(np.sum(d.astype(np.float64) ** 2))


def kmeans(X, K: int, max_iter: int = KMEANS_MAX_ITER, tol: float = KMEANS_TOL,
           semilla: int = SEMILLA, bloque: int = KMEANS_BLOQUE) -> np.ndarray:
    X = np.ascontiguousarray(X, dtype=np.float32)
    if X.ndim != 2:
        raise ValueError(f"X debe ser una matriz, se dio ndim={X.ndim}")
    if len(X) == 0:
        raise ValueError("X no tiene puntos")
    if K <= 0:
        raise ValueError("K debe ser positivo")

    rng = np.random.default_rng(semilla)
    C = kmeans_pp(X, K, rng)
    previa = np.inf

    for _ in range(max(0, int(max_iter))):
        etiquetas, dist = asignar(X, C, bloque)
        actual = float(np.sum(dist.astype(np.float64) ** 2))

        # No comparar contra inf: inf - finito = inf y tol * inf = inf.
        if np.isfinite(previa):
            mejora = previa - actual
            if mejora <= tol * max(previa, 1e-12):
                break

        C = recalcular(X, etiquetas, K, C)
        C = reubicar_vacios(C, X, etiquetas, dist)
        previa = actual

    return C
