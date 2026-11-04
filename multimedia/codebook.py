"""Muestreo, entrenamiento del codebook y asignacion de descriptores.

El codebook es el vocabulario del modelo Bag of Words: ``K`` centroides en el
espacio del descriptor (128-d para SIFT, 19-d para MFCC). Se entrena una sola
vez con ``n_entrenamiento`` objetos explicitos (decision D7) y se reutiliza en
las colecciones de 1k/10k/100k. La huella SHA-1 del codebook permite invalidar
todo lo derivado cuando el vocabulario cambia.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from index.vector.metricas import euclidiana

from . import cache, config
from .kmeans import kmeans




# ---------------------------------------------------------------------------
# Muestreo
# ---------------------------------------------------------------------------
def _rng_objeto(semilla: int, oid) -> np.random.Generator:
    h = int.from_bytes(
        hashlib.sha1(cache.clave_id(oid).encode("utf-8")).digest()[:8], "big",
    )
    return np.random.default_rng([int(semilla), h])


def muestrear_estratificado(pares, orden,
                            total: int = config.MUESTRA_KMEANS,
                            semilla: int = config.SEMILLA,
                            max_por_objeto: int | None = None) -> np.ndarray:
    orden = list(orden)
    n_objetos = len(orden)
    if n_objetos <= 0:
        raise ValueError("orden debe tener al menos un id")
    if total <= 0:
        raise ValueError("total debe ser positivo")

    cupo = max_por_objeto if max_por_objeto is not None else math.ceil(total / n_objetos)
    cupo = max(1, int(cupo))

    elegidos = {}
    for oid, desc in pares:
        desc = np.asarray(desc)
        if len(desc) == 0:
            continue
        k = min(cupo, len(desc))
        if k < len(desc):
            desc = desc[_rng_objeto(semilla, oid).choice(len(desc), size=k, replace=False)]
        elegidos[cache.clave_id(oid)] = np.asarray(desc, dtype=np.float32)

    partes = [elegidos[c] for c in (cache.clave_id(o) for o in orden) if c in elegidos]
    if not partes:
        raise ValueError("no hay descriptores para muestrear")

    muestra = np.concatenate(partes, axis=0)
    if len(muestra) > total:
        idx = np.random.default_rng(int(semilla)).choice(
            len(muestra), size=total, replace=False,
        )
        muestra = muestra[idx]
    return np.ascontiguousarray(muestra, dtype=np.float32)


# ---------------------------------------------------------------------------
# Estandarizacion (solo audio)
# ---------------------------------------------------------------------------
def calcular_estandarizacion(muestra) -> dict:
    muestra = np.asarray(muestra, dtype=np.float64)
    media = muestra.mean(axis=0)
    desv = muestra.std(axis=0)
    desv = np.where(desv < 1e-8, 1.0, desv)
    return {
        "media": media.astype(np.float32),
        "desv": desv.astype(np.float32),
    }


def aplicar_estandarizacion(descriptores, estandarizacion) -> np.ndarray:
    desc = np.asarray(descriptores, dtype=np.float32)
    if len(desc) == 0:
        return np.ascontiguousarray(desc, dtype=np.float32)
    return np.ascontiguousarray(
        (desc - estandarizacion["media"]) / estandarizacion["desv"],
        dtype=np.float32,
    )


# ---------------------------------------------------------------------------
# Artefactos del modelo
# ---------------------------------------------------------------------------
def _ruta_meta(directorio: Path) -> Path:
    return Path(directorio) / "meta.json"


def cargar_meta(tipo: str, base=None, directorio=None) -> dict:
    directorio = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    ruta = _ruta_meta(directorio)
    if not ruta.exists():
        raise FileNotFoundError(
            f"no existe {ruta}; entrene el codebook con entrenar_codebook(...)"
        )
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_meta(directorio: Path, meta: dict) -> None:
    directorio.mkdir(parents=True, exist_ok=True)
    with open(_ruta_meta(directorio), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def validar_meta(meta: dict, tipo: str) -> None:
    config.validar_tipo(tipo)
    if meta.get("tipo") != tipo:
        raise ValueError(f"meta.json es de tipo {meta.get('tipo')!r}, no {tipo!r}")
    if int(meta.get("dim", -1)) != config.dimension(tipo):
        raise ValueError(
            f"meta.json declara dim={meta.get('dim')}, se esperaba {config.dimension(tipo)}"
        )
    if int(meta.get("k", 0)) <= 0:
        raise ValueError("meta.json no tiene un K valido")
    faltantes = [k for k in config.parametros(tipo) if k not in meta]
    if faltantes:
        raise ValueError(f"meta.json incompleto, faltan {faltantes}")


def cargar_codebook(tipo: str, base=None, directorio=None) -> np.ndarray:
    directorio = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    ruta = Path(directorio) / "codebook.npy"
    if not ruta.exists():
        raise FileNotFoundError(f"no existe {ruta}; entrene el codebook primero")
    return np.load(ruta)


def guardar_codebook(directorio: Path, codebook: np.ndarray) -> None:
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    np.save(directorio / "codebook.npy", np.ascontiguousarray(codebook, dtype=np.float32))


def cargar_estandarizacion(tipo: str, base=None, directorio=None) -> dict | None:
    if tipo != "audio":
        return None
    directorio = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    ruta = Path(directorio) / "estandarizacion.npz"
    if not ruta.exists():
        raise FileNotFoundError(f"no existe {ruta}; entrene el codebook de audio primero")
    with np.load(ruta) as z:
        return {
            "media": np.array(z["media"], dtype=np.float32),
            "desv": np.array(z["desv"], dtype=np.float32),
        }


def guardar_estandarizacion(directorio: Path, estandarizacion: dict) -> None:
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    np.savez(
        directorio / "estandarizacion.npz",
        media=np.asarray(estandarizacion["media"], dtype=np.float32),
        desv=np.asarray(estandarizacion["desv"], dtype=np.float32),
    )


def huella(codebook) -> str:
    datos = np.ascontiguousarray(codebook, dtype=np.float32).tobytes()
    return hashlib.sha1(datos).hexdigest()


def _invalidar_derivados(directorio: Path, huella_nueva: str) -> None:
    import shutil

    carpeta_hist = Path(directorio) / "histogramas"
    if carpeta_hist.exists():
        prefijo = huella_nueva[:12]
        for ruta in carpeta_hist.glob("*.npz"):
            if not ruta.name.startswith(prefijo):
                try:
                    ruta.unlink()
                except OSError:
                    pass

    carpeta_colecciones = Path(directorio) / "colecciones"
    if carpeta_colecciones.exists():
        shutil.rmtree(carpeta_colecciones, ignore_errors=True)

    # El modelo viejo puede seguir cargado en memoria en este proceso.
    from . import bovw

    bovw.limpiar_extractores()


def _huella_entrenamiento(tipo: str, K: int, muestra: int, semilla: int,
                          parametros: dict, ids, huellas) -> str:
    h = hashlib.sha1()
    cabecera = json.dumps(
        {
            "tipo": tipo, "K": int(K), "muestra": int(muestra),
            "semilla": int(semilla), "params": parametros,
            "muestreo": "por_id_v1",
        },
        sort_keys=True, ensure_ascii=False,
    )
    h.update(cabecera.encode("utf-8"))
    for oid, huella_archivo in zip(ids, huellas):
        h.update(f"\n{cache.clave_id(oid)}\t{huella_archivo}".encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Entrenamiento
# ---------------------------------------------------------------------------
def entrenar_codebook(tipo: str, objetos=None, base=None, K: int | None = None, *,
                      directorio=None, cache_dir=None,
                      ids_entrenamiento=None,
                      n_entrenamiento: int | None = None,
                      muestra: int = config.MUESTRA_KMEANS,
                      semilla: int = config.SEMILLA,
                      workers: int | None = None,
                      reintentar_errores: bool = False,
                      forzar: bool = False,
                      params: dict | None = None,
                      **cache_params) -> np.ndarray:
    tipo = config.validar_tipo(tipo)
    modelo_dir = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    modelo_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(cache_dir) if cache_dir is not None else modelo_dir / "cache"

    params = {**(params or {}), **cache_params}
    info_cache = cache.resumen_cache(tipo, directorio=cache_dir)
    params_cache = info_cache.get("params", {})
    if params and params_cache:
        distintos = {
            k: (params_cache.get(k), v)
            for k, v in params.items() if params_cache.get(k) != v
        }
        if distintos:
            raise ValueError(
                f"params no coincide con la cache existente: {distintos}; "
                "extraiga de nuevo o use los mismos parametros"
            )
    parametros = {**config.parametros(tipo), **params_cache, **params}

    if objetos is not None:
        cache.sincronizar(
            tipo, objetos, directorio=cache_dir, workers=workers,
            reintentar_errores=reintentar_errores, **params,
        )

    shards = cache._indices_shards(cache_dir)
    if shards and not (cache_dir / cache.NOMBRE_MANIFIESTO).exists():
        raise ValueError(
            f"cache de version 1 en {cache_dir}: borrela y ejecute construir.py de nuevo"
        )

    ids_cache = cache.ids_objetos(tipo, directorio=cache_dir)
    if not ids_cache:
        raise ValueError(
            f"la cache de {cache_dir} no contiene objetos vigentes; "
            "pase objetos o ejecute construir.py primero"
        )

    if ids_entrenamiento is not None:
        ids = cache.expandir_ids(tipo, list(ids_entrenamiento), directorio=cache_dir)
    elif n_entrenamiento is not None:
        n_entrenamiento = int(n_entrenamiento)
        if n_entrenamiento <= 0:
            raise ValueError("n_entrenamiento debe ser positivo")
        if n_entrenamiento > len(ids_cache):
            raise ValueError(
                f"se pidieron {n_entrenamiento} objetos para entrenar y la cache "
                f"solo tiene {len(ids_cache)}"
            )
        ids = ids_cache[:n_entrenamiento]
    else:
        ids = ids_cache

    K = int(K or config.k_por_defecto(tipo))
    huellas = cache.huellas_de_ids(tipo, ids, directorio=cache_dir)
    huella_ent = _huella_entrenamiento(
        tipo, K, muestra, semilla, parametros, ids, huellas,
    )

    meta_previo = {}
    if _ruta_meta(modelo_dir).exists():
        try:
            meta_previo = cargar_meta(tipo, directorio=modelo_dir)
        except (OSError, ValueError):
            meta_previo = {}

    ruta_codebook = modelo_dir / "codebook.npy"
    if (not forzar and meta_previo.get("huella_entrenamiento") == huella_ent
            and ruta_codebook.exists()):
        try:
            codebook_previo = np.load(ruta_codebook)
            if huella(codebook_previo) == meta_previo.get("huella_codebook"):
                return codebook_previo
        except (OSError, ValueError):
            pass

    muestra_desc = muestrear_estratificado(
        cache.iterar(tipo, ids, directorio=cache_dir),   # se lee por shard
        ids,                                             # pero el resultado sigue el orden de ids
        total=muestra, semilla=semilla,
    )

    estandarizacion = None
    if tipo == "audio":
        estandarizacion = calcular_estandarizacion(muestra_desc)
        muestra_desc = aplicar_estandarizacion(muestra_desc, estandarizacion)

    if K > len(muestra_desc):
        raise ValueError(
            f"K={K} no puede superar la muestra de {len(muestra_desc)} descriptores"
        )

    codebook = kmeans(muestra_desc, K, semilla=semilla)
    huella_nueva = huella(codebook)

    guardar_codebook(modelo_dir, codebook)
    if estandarizacion is not None:
        guardar_estandarizacion(modelo_dir, estandarizacion)
    np.save(modelo_dir / "entrenamiento_ids.npy", cache.crear_array_ids(ids))

    meta = {
        **parametros,
        "tipo": tipo,
        "descriptor": "mfcc" if tipo == "audio" else "sift",
        "dim": config.dimension(tipo),
        "k": int(len(codebook)),
        "muestra_kmeans": int(len(muestra_desc)),
        "muestra_objetivo": int(muestra),
        "cache_objetos": int(len(ids_cache)),
        "n_entrenamiento": int(len(ids)),
        "semilla": int(semilla),
        "huella_entrenamiento": huella_ent,
        "huella_codebook": huella_nueva,
        "version": 3,
    }
    guardar_meta(modelo_dir, meta)

    if meta_previo.get("huella_codebook") != huella_nueva:
        _invalidar_derivados(modelo_dir, huella_nueva)

    return codebook


# ---------------------------------------------------------------------------
# Asignacion e histogramas
# ---------------------------------------------------------------------------
def histograma(desc, codebook) -> np.ndarray:
    codebook = np.asarray(codebook, dtype=np.float32)
    K = len(codebook)
    desc = np.asarray(desc, dtype=np.float32)
    if len(desc) == 0:
        return np.zeros(K, dtype=np.int64)
    if desc.ndim != 2 or desc.shape[1] != codebook.shape[1]:
        raise ValueError(
            f"descriptor de dimension {desc.shape}, codebook de dimension {codebook.shape}"
        )
    palabras = euclidiana(desc, codebook).argmin(axis=1)
    return np.bincount(palabras, minlength=K).astype(np.int64)
