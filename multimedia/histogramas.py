import os
from pathlib import Path

import numpy as np

from . import cache, codebook, config

NOMBRE = "histogramas"


def directorio_histogramas(modelo_dir) -> Path:
    return Path(modelo_dir) / NOMBRE


def ruta_histogramas(modelo_dir, huella_codebook: str) -> Path:
    return directorio_histogramas(modelo_dir) / f"{huella_codebook[:12]}.npz"


def _resolver_directorios(tipo: str, base, directorio, cache_dir):
    modelo_dir = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    cache_dir = Path(cache_dir) if cache_dir is not None else modelo_dir / "cache"
    return modelo_dir, cache_dir


def _cargar(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    with np.load(ruta, allow_pickle=True) as z:
        ids = [cache.normalizar_id(v) for v in z["ids"]]
        # Se mantiene uint16 (D-P) para no duplicar la memoria en int64.
        conteos = np.asarray(z["conteos"], dtype=np.uint16)
        huellas = [str(v) for v in z["huellas_archivo"]]
    return {"ids": ids, "conteos": conteos, "huellas": huellas}


def _como_uint16(conteo) -> np.ndarray:
    conteo = np.asarray(conteo)
    if conteo.size and int(conteo.max()) > np.iinfo(np.uint16).max:
        raise ValueError("los conteos superan uint16; reduzca nfeatures/segmentos")
    return conteo.astype(np.uint16, copy=False)


def _guardar(ruta: Path, ids, conteos, huellas) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conteos = np.asarray(conteos)
    if conteos.size and int(conteos.max()) > np.iinfo(np.uint16).max:
        raise ValueError("los conteos superan uint16; reduzca nfeatures/segmentos")
    temporal = ruta.with_name(ruta.stem + ".tmp.npz")
    np.savez(
        temporal,
        ids=cache.crear_array_ids(ids),
        conteos=conteos.astype(np.uint16),
        huellas_archivo=np.asarray(huellas, dtype=object),
    )
    os.replace(temporal, ruta)


def _cargar_modelo(tipo: str, modelo_dir: Path):
    meta = codebook.cargar_meta(tipo, directorio=modelo_dir)
    codebook.validar_meta(meta, tipo)
    huella = meta.get("huella_codebook")
    if not huella:
        raise ValueError(
            f"{modelo_dir / 'meta.json'} no tiene huella_codebook; "
            "reentrene el codebook con entrenar_codebook(...)"
        )
    cb = codebook.cargar_codebook(tipo, directorio=modelo_dir)
    if codebook.huella(cb) != huella:
        raise ValueError(
            "codebook.npy no coincide con la huella de meta.json; "
            "reentrene el codebook para regenerar ambos"
        )
    estandarizacion = codebook.cargar_estandarizacion(tipo, directorio=modelo_dir)
    return meta, cb, estandarizacion, huella


def actualizar_histogramas(tipo: str, ids=None, base=None, *, directorio=None,
                           cache_dir=None, forzar: bool = False) -> dict:

    tipo = config.validar_tipo(tipo)
    modelo_dir, cache_dir = _resolver_directorios(tipo, base, directorio, cache_dir)
    _meta, cb, estandarizacion, huella = _cargar_modelo(tipo, modelo_dir)

    if ids is None:
        ids = cache.ids_objetos(tipo, base=base, directorio=cache_dir)
    ids = [cache.normalizar_id(v) for v in ids]

    # Sin duplicados, conservando el orden pedido.
    vistos = set()
    unicos = []
    for oid in ids:
        clave = cache.clave_id(oid)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(oid)
    ids = unicos
    if not ids:
        raise ValueError("no hay objetos para calcular histogramas")

    huellas = cache.huellas_de_ids(tipo, ids, base=base, directorio=cache_dir)
    ruta = ruta_histogramas(modelo_dir, huella)
    existente = _cargar(ruta)
    if existente is None:
        K = len(cb)
        existente = {
            "ids": [], "conteos": np.zeros((0, K), dtype=np.uint16), "huellas": [],
        }
    if existente["conteos"].shape[1] != len(cb):
        raise ValueError(
            f"el archivo de histogramas tiene K={existente['conteos'].shape[1]} "
            f"y el codebook K={len(cb)}"
        )

    posicion = {cache.clave_id(oid): i for i, oid in enumerate(existente["ids"])}

    pendientes = []
    for oid, huella_archivo in zip(ids, huellas):
        clave = cache.clave_id(oid)
        i = posicion.get(clave)
        if i is not None and not forzar and existente["huellas"][i] == huella_archivo:
            continue
        pendientes.append((oid, huella_archivo))

    nuevos = {}
    if pendientes:
        for oid, desc in cache.iterar(
            tipo, [oid for oid, _ in pendientes], base=base, directorio=cache_dir,
        ):
            if tipo == "audio":
                desc = codebook.aplicar_estandarizacion(desc, estandarizacion)
            nuevos[cache.clave_id(oid)] = codebook.histograma(desc, cb)

    cambiados = 0
    filas_nuevas, ids_nuevos, huellas_nuevas = [], [], []
    for oid, huella_archivo in zip(ids, huellas):
        clave = cache.clave_id(oid)
        if clave not in nuevos:
            continue
        conteo = nuevos[clave]
        i = posicion.get(clave)
        if i is None:
            # Acumular y apilar una sola vez: vstack por fila era cuadratico.
            posicion[clave] = len(existente["ids"]) + len(ids_nuevos)
            ids_nuevos.append(oid)
            filas_nuevas.append(_como_uint16(conteo))
            huellas_nuevas.append(huella_archivo)
        else:
            existente["conteos"][i] = _como_uint16(conteo)
            existente["huellas"][i] = huella_archivo
            cambiados += 1

    if filas_nuevas:
        existente["conteos"] = np.vstack([existente["conteos"], np.stack(filas_nuevas)])
        existente["ids"].extend(ids_nuevos)
        existente["huellas"].extend(huellas_nuevas)
    agregados = len(filas_nuevas)

    if pendientes or not ruta.exists():
        _guardar(ruta, existente["ids"], existente["conteos"], existente["huellas"])

    return {
        "tipo": tipo,
        "huella_codebook": huella,
        "ruta": str(ruta),
        "total": len(existente["ids"]),
        "agregados": agregados,
        "cambiados": cambiados,
        "reutilizados": len(ids) - len(pendientes),
    }


def conteos(tipo: str, ids, base=None, *, directorio=None) -> tuple[np.ndarray, list[str]]:

    tipo = config.validar_tipo(tipo)
    modelo_dir = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    _meta, cb, _est, huella = _cargar_modelo(tipo, modelo_dir)
    ruta = ruta_histogramas(modelo_dir, huella)
    datos = _cargar(ruta)
    if datos is None:
        raise FileNotFoundError(
            f"no existen histogramas en {ruta}; ejecute actualizar_histogramas(...)"
        )

    posicion = {cache.clave_id(oid): i for i, oid in enumerate(datos["ids"])}
    filas = []
    huellas = []
    faltantes = []
    for oid in ids:
        clave = cache.clave_id(oid)
        i = posicion.get(clave)
        if i is None:
            faltantes.append(oid)
            continue
        filas.append(datos["conteos"][i])
        huellas.append(datos["huellas"][i])
    if faltantes:
        raise KeyError(
            f"faltan {len(faltantes)} histogramas (por ejemplo {faltantes[0]!r}); "
            "ejecute actualizar_histogramas(...) antes de construir la coleccion"
        )

    C = np.vstack(filas) if filas else np.zeros((0, len(cb)), dtype=np.uint16)
    return C, huellas
