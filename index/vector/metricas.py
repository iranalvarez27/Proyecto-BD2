import numpy as np

# las tres son distancias: menor es mas cerca
METRICAS = ("euclidean", "cosine", "dot")


def validar_metrica(metrica: str) -> None:
    if metrica not in METRICAS:
        raise ValueError(f"metrica debe ser una de {list(METRICAS)}, se dio {metrica!r}")


def _consultas(consultas) -> np.ndarray:
    q = np.asarray(consultas, dtype=np.float32)
    if q.ndim == 1:
        q = q[None, :]
    if q.ndim != 2:
        raise ValueError(f"consultas debe ser un vector o una matriz, se dio ndim={q.ndim}")
    return q


def _par(consultas, vectores) -> tuple[np.ndarray, np.ndarray]:
    q = _consultas(consultas)
    x = np.asarray(vectores, dtype=np.float32)
    if x.ndim != 2:
        raise ValueError(f"vectores debe ser una matriz N x K, se dio ndim={x.ndim}")
    if q.shape[1] != x.shape[1]:
        raise ValueError(f"dimension distinta: consultas {q.shape[1]}, vectores {x.shape[1]}")
    return q, x


def normas(vectores) -> np.ndarray:
    x = np.asarray(vectores, dtype=np.float32)
    return np.sqrt(np.einsum("ij,ij->i", x, x))


def euclidiana(consultas, vectores) -> np.ndarray:
    q, x = _par(consultas, vectores)
    # ||q - x||^2 = ||q||^2 + ||x||^2 - 2 q.x
    d2 = np.einsum("ij,ij->i", q, q)[:, None] + np.einsum("ij,ij->i", x, x)[None, :] - 2 * (q @ x.T)
    np.maximum(d2, 0, out=d2)
    return np.sqrt(d2, out=d2)


def coseno(consultas, vectores) -> np.ndarray:
    q, x = _par(consultas, vectores)
    producto = q @ x.T
    denominador = np.outer(normas(q), normas(x))
    # un vector nulo tiene similitud 0 con todo, distancia 1
    similitud = np.divide(producto, denominador, out=np.zeros_like(producto), where=denominador > 0)
    return np.clip(1 - similitud, 0, 2)


def producto_punto(consultas, vectores) -> np.ndarray:
    q, x = _par(consultas, vectores)
    return -(q @ x.T)


def distancias(consultas, vectores, metrica: str) -> np.ndarray:
    validar_metrica(metrica)
    if metrica == "euclidean":
        return euclidiana(consultas, vectores)
    if metrica == "cosine":
        return coseno(consultas, vectores)
    return producto_punto(consultas, vectores)
