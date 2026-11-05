import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parent.parent
# Se puede sobreescribir con MULTIMEDIA_DATA para experimentos aislados.
BASE = Path(os.environ.get("MULTIMEDIA_DATA", RAIZ / "data" / "multimedia"))

# ---------------------------------------------------------------------------
# Parametros generales
# ---------------------------------------------------------------------------
SEMILLA = 42
TAMANOS = (1_000, 10_000, 100_000)
SHARD = 1_000
MUESTRA_KMEANS = 200_000
KMEANS_MAX_ITER = 100
KMEANS_TOL = 1e-4
KMEANS_BLOQUE = 20_000

# Cache versionada por id (seccion 8.8 del plan).
VERSION_CACHE = 2
# Un objeto modificado o eliminado deja descriptores obsoletos en los shards
# (append-only). Cuando superan este porcentaje, compactar() reescribe todo.
UMBRAL_COMPACTAR = 0.30
# Shards entre checkpoints del manifiesto (P3, seccion 9.2). Ante una caida se
# pierde como maximo el registro de estos shards, que se vuelven a extraer.
MANIFIESTO_CADA = 10

# K inicial del plan; F10 puede ajustarlo con la busqueda en cuadricula.
K_IMAGEN = 512
K_AUDIO = 256

# ---------------------------------------------------------------------------
# Imagenes (SIFT)
# ---------------------------------------------------------------------------
DIM_IMAGEN = 128
MAX_LADO = 512
NFEATURES = 500

# ---------------------------------------------------------------------------
# Audio (MFCC)
# ---------------------------------------------------------------------------
DIM_AUDIO = 19
SR = 22_050
N_FFT = 2_048
HOP = 512
N_MFCC = 20          # se descarta c0 -> 19 dimensiones utiles
SEG_S = 2.0          # Para el apendice C dice 5 segundos.

EXTENSIONES_IMAGEN = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".gif")
EXTENSIONES_AUDIO = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aiff", ".aif")


def tipo_por_extension(ruta) -> str:
    sufijo = Path(str(ruta)).suffix.lower()
    if sufijo in EXTENSIONES_AUDIO:
        return "audio"
    if sufijo in EXTENSIONES_IMAGEN:
        return "imagen"
    soportadas = ", ".join(EXTENSIONES_IMAGEN + EXTENSIONES_AUDIO)
    raise ValueError(
        f"extension {sufijo or '(sin extension)'} no reconocida en {ruta!r}; "
        f"extensiones soportadas: {soportadas}. Pase tipo='imagen' o 'audio' "
        "si el archivo es valido."
    )


def validar_tipo(tipo: str) -> str:
    if tipo not in ("imagen", "audio"):
        raise ValueError(f"tipo debe ser 'imagen' o 'audio', se dio {tipo!r}")
    return tipo


def dimension(tipo: str) -> int:
    return DIM_AUDIO if validar_tipo(tipo) == "audio" else DIM_IMAGEN


def k_por_defecto(tipo: str) -> int:
    return K_AUDIO if validar_tipo(tipo) == "audio" else K_IMAGEN


def parametros(tipo: str) -> dict:
    validar_tipo(tipo)
    if tipo == "audio":
        return {"sr": SR, "n_fft": N_FFT, "hop": HOP, "n_mfcc": N_MFCC, "seg_s": SEG_S}
    return {"max_lado": MAX_LADO, "nfeatures": NFEATURES}


def directorio_modelo(tipo: str, base=None) -> Path:
    return Path(base or BASE) / validar_tipo(tipo)


def directorio_cache(tipo: str, base=None) -> Path:
    return directorio_modelo(tipo, base) / "cache"


def directorio_histogramas(tipo: str, base=None) -> Path:
    return directorio_modelo(tipo, base) / "histogramas"


def directorio_colecciones(tipo: str, base=None) -> Path:
    return directorio_modelo(tipo, base) / "colecciones"


def directorio_coleccion(tipo: str, N: int, base=None) -> Path:
    return directorio_colecciones(tipo, base) / str(int(N))

