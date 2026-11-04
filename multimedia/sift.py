import cv2
import numpy as np

from .config import MAX_LADO, NFEATURES


def extraer_sift(ruta, max_lado: int = MAX_LADO, nfeatures: int = NFEATURES) -> np.ndarray:
    if max_lado <= 0:
        raise ValueError("max_lado debe ser positivo")
    if nfeatures <= 0:
        raise ValueError("nfeatures debe ser positivo")

    img = cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"no se pudo leer {ruta}")

    escala = max_lado / max(img.shape)
    if escala < 1:
        img = cv2.resize(img, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)

    _, desc = cv2.SIFT_create(nfeatures=nfeatures).detectAndCompute(img, None)
    if desc is None:
        return np.empty((0, 128), np.uint8)

    # OpenCV devuelve float32 en [0, 255]; redondear a uint8 no pierde
    # informacion relevante y reduce la cache a la cuarta parte.
    return np.clip(np.rint(desc), 0, 255).astype(np.uint8)
