import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np

from index.tfidf import idf, vector_tfidf

from . import cache, codebook, config, histogramas
from .mfcc import cargar_audio, extraer_mfcc, segmentos_de_senal
from .sift import extraer_sift


# ---------------------------------------------------------------------------
# TF-IDF
# ---------------------------------------------------------------------------
def calcular_idf(C) -> np.ndarray:
    C = np.asarray(C)
    if C.ndim != 2:
        raise ValueError("C debe ser una matriz N x K")
    N = len(C)
    K = C.shape[1]
    if N == 0:
        return np.zeros(K, dtype=np.float32)
    df = (C > 0).sum(axis=0)
    return np.array([idf(N, int(d)) for d in df], dtype=np.float32)


def tfidf_denso(conteos, idf_vec) -> np.ndarray:
    conteos = np.asarray(conteos)
    idf_vec = np.asarray(idf_vec, dtype=np.float32)
    if conteos.ndim != 1:
        raise ValueError("conteos debe ser un histograma de una dimension")
    if len(conteos) != len(idf_vec):
        raise ValueError(
            f"conteos tiene {len(conteos)} palabras e idf tiene {len(idf_vec)}"
        )

    pesos = vector_tfidf(
        {j: int(c) for j, c in enumerate(conteos) if c},
        {j: float(w) for j, w in enumerate(idf_vec)},
        tipo_tf="relativo",
    )
    v = np.zeros(len(idf_vec), dtype=np.float32)
    for j, w in pesos.items():
        v[j] = w
    return v


# ---------------------------------------------------------------------------
# Rutas de una coleccion
# ---------------------------------------------------------------------------
def carpeta_coleccion(modelo_dir, N: int) -> Path:
    return Path(modelo_dir) / "colecciones" / str(int(N))


def _guardar_npy(ruta: Path, arreglo, allow_pickle: bool = False) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.stem + ".tmp.npy")
    np.save(temporal, arreglo, allow_pickle=allow_pickle)
    os.replace(temporal, ruta)


def _leer_json(ruta) -> dict:
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _huella_coleccion(huella_codebook: str, ids, huellas) -> str:
    h = hashlib.sha1()
    h.update(huella_codebook.encode("utf-8"))
    for oid, huella in zip(ids, huellas):
        h.update(f"\n{cache.clave_id(oid)}\t{huella}".encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Construccion de una coleccion
# ---------------------------------------------------------------------------
def construir_coleccion(tipo: str, N: int, base=None, *, ids=None,
                        K: int | None = None, directorio=None, cache_dir=None,
                        objetos=None, workers: int | None = None,
                        forzar: bool = False,
                        reintentar_errores: bool = False,
                        params: dict | None = None) -> dict:
    tipo = config.validar_tipo(tipo)
    N = int(N)
    if N <= 0:
        raise ValueError("N debe ser positivo")

    modelo_dir = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    modelo_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(cache_dir) if cache_dir is not None else modelo_dir / "cache"

    if objetos is not None:
        cache.sincronizar(
            tipo, objetos, directorio=cache_dir, workers=workers,
            reintentar_errores=reintentar_errores, **(params or {}),
        )

    ruta_meta = modelo_dir / "meta.json"
    if not ruta_meta.exists():
        raise ValueError(
            f"no existe {ruta_meta}; entrene el codebook primero con "
            f"entrenar_codebook({tipo!r}, n_entrenamiento=...)"
        )

    meta = codebook.cargar_meta(tipo, directorio=modelo_dir)
    codebook.validar_meta(meta, tipo)
    params_cache = cache.resumen_cache(tipo, directorio=cache_dir).get("params", {})
    if params_cache:
        distintos = {
            k: (meta.get(k), v) for k, v in params_cache.items()
            if meta.get(k) != v
        }
        if distintos:
            raise ValueError(
                f"el codebook se entreno con otros parametros de extraccion: "
                f"{distintos}; reentrene el codebook sobre esta cache"
            )
    if params:
        distintos = {
            k: (meta.get(k), v) for k, v in params.items() if meta.get(k) != v
        }
        if distintos:
            raise ValueError(
                f"params no coincide con el codebook entrenado: {distintos}; "
                "reentrene el modelo o use los mismos parametros"
            )
    huella_cb = meta.get("huella_codebook")
    if not huella_cb:
        raise ValueError(
            f"{ruta_meta} no tiene huella_codebook; reentrene el codebook con "
            "entrenar_codebook(...) para poder validar los vectores"
        )
    cb = codebook.cargar_codebook(tipo, directorio=modelo_dir)
    if codebook.huella(cb) != huella_cb:
        raise ValueError(
            "codebook.npy no coincide con la huella de meta.json; "
            "reentrene el codebook para regenerar ambos"
        )
    if K is not None and int(K) != len(cb):
        raise ValueError(
            f"se pidio K={K} pero el codebook entrenado tiene K={len(cb)}"
        )

    if ids is None:
        disponibles = cache.ids_objetos(tipo, directorio=cache_dir)
        if len(disponibles) < N:
            raise ValueError(
                f"la cache solo tiene {len(disponibles)} objetos vigentes y se "
                f"pidieron {N}; sincronice mas archivos primero"
            )
        ids = disponibles[:N]
    else:
        ids = list(ids)
        if len(ids) < N:
            raise ValueError(
                f"se pidieron {N} ids y solo se recibieron {len(ids)}"
            )
        ids = ids[:N]

    huellas = cache.huellas_de_ids(tipo, ids, directorio=cache_dir)
    huella_col = _huella_coleccion(huella_cb, ids, huellas)

    carpeta = carpeta_coleccion(modelo_dir, N)
    ruta_idf = carpeta / "idf.npy"
    ruta_vec = carpeta / "vectores.npy"
    ruta_ids = carpeta / "ids.npy"
    ruta_info = carpeta / "coleccion.json"

    if not forzar and ruta_idf.exists() and ruta_vec.exists() and ruta_ids.exists():
        info = _leer_json(ruta_info)
        if info.get("huella_coleccion") == huella_col:
            try:
                vectores = np.load(ruta_vec)
                ids_guardados = np.load(ruta_ids, allow_pickle=True)
                idf_vec = np.load(ruta_idf)
                if (vectores.shape == (N, len(cb))
                        and len(ids_guardados) == N
                        and idf_vec.shape == (len(cb),)):
                    return {
                        "tipo": tipo, "N": N, "K": int(len(cb)),
                        "idf": str(ruta_idf), "vectores": str(ruta_vec),
                        "ids": str(ruta_ids), "reutilizado": True,
                        "huella_coleccion": huella_col,
                    }
            except (OSError, ValueError):
                pass

    histogramas.actualizar_histogramas(
        tipo, ids, base=base, directorio=modelo_dir, cache_dir=cache_dir,
        forzar=forzar,
    )
    C, huellas_calculadas = histogramas.conteos(tipo, ids, base=base, directorio=modelo_dir)
    if huellas_calculadas != huellas:
        raise ValueError(
            "la cache cambio mientras se construia la coleccion; vuelva a intentarlo"
        )

    idf_vec = calcular_idf(C)
    K_real = len(cb)
    vectores = np.empty((N, K_real), dtype=np.float32)
    for i in range(N):
        vectores[i] = tfidf_denso(C[i], idf_vec)

    _guardar_npy(ruta_idf, np.asarray(idf_vec, dtype=np.float32))
    _guardar_npy(ruta_vec, vectores)
    # Los ids pueden ser cadenas o tuplas (audio): arreglo de objetos.
    _guardar_npy(ruta_ids, cache.crear_array_ids(ids), allow_pickle=True)

    info = {
        "tipo": tipo,
        "N": N,
        "K": K_real,
        "huella_codebook": huella_cb,
        "huella_coleccion": huella_col,
        "descriptores": int(C.sum()),
        "fecha": datetime.now().isoformat(timespec="seconds"),
    }
    _guardar_json(ruta_info, info)

    return {
        "tipo": tipo, "N": N, "K": K_real,
        "idf": str(ruta_idf), "vectores": str(ruta_vec),
        "ids": str(ruta_ids), "reutilizado": False,
        "descriptores": int(C.sum()),
        "huella_coleccion": huella_col,
    }


def _guardar_json(ruta, datos) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)


def cargar_coleccion(tipo: str, N: int, base=None, directorio=None) -> tuple[np.ndarray, np.ndarray]:
    modelo_dir = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    carpeta = carpeta_coleccion(modelo_dir, N)
    ruta_vec = carpeta / "vectores.npy"
    ruta_ids = carpeta / "ids.npy"
    if not ruta_vec.exists() or not ruta_ids.exists():
        raise FileNotFoundError(
            f"no existen los vectores de {tipo} con N={N}; ejecute construir_coleccion(...)"
        )
    vectores = np.load(ruta_vec)
    ids_crudos = np.load(ruta_ids, allow_pickle=True)
    ids = cache.crear_array_ids([cache.normalizar_id(v) for v in ids_crudos])
    return vectores, ids


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def _n_mas_grande(modelo_dir: Path) -> int:
    carpeta = Path(modelo_dir) / "colecciones"
    tamanos = []
    if carpeta.exists():
        for ruta in carpeta.glob("*/idf.npy"):
            sufijo = ruta.parent.name
            if sufijo.isdigit():
                tamanos.append(int(sufijo))
    if not tamanos:
        raise FileNotFoundError(
            f"no hay colecciones en {modelo_dir}; construya primero una con "
            "construir_coleccion(...)"
        )
    return max(tamanos)


def _resolver_n(tipo: str, n_coleccion, base=None, directorio=None) -> int:
    if n_coleccion is not None:
        return int(n_coleccion)
    modelo_dir = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    return _n_mas_grande(modelo_dir)


def n_coleccion_vigente(tipo: str, base=None, directorio=None) -> int:
    return _resolver_n(config.validar_tipo(tipo), None, base, directorio)


def _mtime_ns(ruta) -> int | None:
    try:
        return os.stat(ruta).st_mtime_ns
    except OSError:
        return None


class Extractor:
    def __init__(self, tipo: str, n_coleccion: int | None = None, base=None, directorio=None):
        tipo = config.validar_tipo(tipo)
        self.tipo = tipo
        self.directorio = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
        self.n_coleccion = _resolver_n(tipo, n_coleccion, base, directorio)
        self.ruta_meta = self.directorio / "meta.json"
        self.carpeta = carpeta_coleccion(self.directorio, self.n_coleccion)
        self.ruta_info = self.carpeta / "coleccion.json"

        self.meta = codebook.cargar_meta(tipo, directorio=self.directorio)
        codebook.validar_meta(self.meta, tipo)
        huella = self.meta.get("huella_codebook")
        if not huella:
            raise ValueError(
                f"{self.ruta_meta} no tiene huella_codebook; "
                "reentrene el codebook con entrenar_codebook(...)"
            )

        self.codebook = codebook.cargar_codebook(tipo, directorio=self.directorio)
        if codebook.huella(self.codebook) != huella:
            raise ValueError(
                "codebook.npy no coincide con la huella de meta.json; "
                "reentrene el codebook para regenerar ambos"
            )
        self.estandarizacion = codebook.cargar_estandarizacion(tipo, directorio=self.directorio)

        ruta_idf = self.carpeta / "idf.npy"
        if not ruta_idf.exists():
            raise FileNotFoundError(
                f"no existe {ruta_idf}; construya primero la coleccion de {self.n_coleccion}"
            )
        info = _leer_json(self.ruta_info)
        if info.get("huella_codebook") != huella:
            raise ValueError(
                f"la coleccion de {self.n_coleccion} se calculo con otro codebook; "
                f"reconstruyala con construir_coleccion({tipo!r}, {self.n_coleccion}, forzar=True)"
            )
        self.idf = np.load(ruta_idf)

        if self.codebook.shape[1] != int(self.meta["dim"]):
            raise ValueError("la dimension del codebook no coincide con meta.json")
        if self.codebook.shape[0] != int(self.meta["k"]):
            raise ValueError(
                f"meta.json declara K={self.meta['k']} y el codebook tiene {self.codebook.shape[0]} filas"
            )
        if self.codebook.shape[0] != len(self.idf):
            raise ValueError(
                f"codebook con K={self.codebook.shape[0]} e IDF con K={len(self.idf)}"
            )
        self._firma = self.firma()

    def firma(self) -> tuple:
        return (_mtime_ns(self.ruta_meta), _mtime_ns(self.ruta_info))

    def obsoleto(self) -> bool:
        return self.firma() != self._firma

    def descriptores(self, ruta, segmento: int | None = None):
        if self.tipo == "imagen":
            if segmento is not None:
                raise ValueError("segmento solo aplica a audio")
            return extraer_sift(
                ruta, int(self.meta["max_lado"]), int(self.meta["nfeatures"]),
            )

        y = cargar_audio(ruta, int(self.meta["sr"]))
        if segmento is not None:
            segmentos = segmentos_de_senal(
                y, int(self.meta["sr"]), float(self.meta.get("seg_s", config.SEG_S)),
            )
            indice = int(segmento)
            if not 0 <= indice < len(segmentos):
                raise ValueError(
                    f"segmento {indice} fuera de rango: el archivo tiene "
                    f"{len(segmentos)} segmentos completos"
                )
            y = segmentos[indice]

        m = extraer_mfcc(
            y,
            sr=int(self.meta["sr"]),
            n_fft=int(self.meta["n_fft"]),
            hop=int(self.meta["hop"]),
            n_mfcc=int(self.meta["n_mfcc"]),
        )
        return codebook.aplicar_estandarizacion(m, self.estandarizacion)

    def __call__(self, ruta, segmento: int | None = None) -> np.ndarray:
        conteos = codebook.histograma(self.descriptores(ruta, segmento), self.codebook)
        return tfidf_denso(conteos, self.idf)


_EXTRACTORES: dict[tuple, Extractor] = {}


def _clave(tipo: str, n_coleccion: int, base, directorio) -> tuple:
    if directorio is not None:
        destino = ("directorio", str(Path(directorio).resolve()))
    else:
        destino = ("base", str(Path(base or config.BASE).resolve()))
    return (tipo, int(n_coleccion), destino)


def _extractor(tipo: str, n_coleccion: int, base=None, directorio=None) -> Extractor:
    clave = _clave(tipo, n_coleccion, base, directorio)
    actual = _EXTRACTORES.get(clave)
    # N3: otro proceso pudo reentrenar o reconstruir la coleccion. Un stat()
    # por consulta es despreciable y evita mezclar modelos.
    if actual is not None and actual.obsoleto():
        _EXTRACTORES.pop(clave, None)
        actual = None
    if actual is None:
        actual = Extractor(tipo, n_coleccion, base=base, directorio=directorio)
        _EXTRACTORES[clave] = actual
    return actual


def limpiar_extractores() -> None:
    _EXTRACTORES.clear()


def ExtractFeatures(objeto, tipo: str | None = None, n_coleccion: int | None = None,
                    base=None, directorio=None, segmento: int | None = None) -> np.ndarray:
    tipo = config.validar_tipo(tipo or config.tipo_por_extension(objeto))
    n_coleccion = _resolver_n(tipo, n_coleccion, base, directorio)
    return _extractor(tipo, n_coleccion, base=base, directorio=directorio)(objeto, segmento)


def _segmento_de_id(oid):
    if isinstance(oid, tuple) and len(oid) == 2:
        try:
            return int(oid[1])
        except (TypeError, ValueError):
            return None
    return None


def verificar_consistencia(tipo: str, ruta, fila: int, n_coleccion: int | None = None,
                           base=None, directorio=None, segmento: int | None = None,
                           tolerancia: float = 0.0) -> dict:
    tipo = config.validar_tipo(tipo)
    n_coleccion = _resolver_n(tipo, n_coleccion, base, directorio)
    vectores, ids = cargar_coleccion(tipo, n_coleccion, base=base, directorio=directorio)
    oid = ids[int(fila)]

    if segmento is not None:
        if tipo != "audio":
            raise ValueError("segmento solo aplica a audio")
        esperado_segmento = _segmento_de_id(oid)
        if esperado_segmento is not None and esperado_segmento != int(segmento):
            raise ValueError(
                f"la fila {fila} es el segmento {esperado_segmento} de {oid!r}, "
                f"no el {segmento}"
            )

    consulta = ExtractFeatures(
        ruta, tipo=tipo, n_coleccion=n_coleccion, base=base, directorio=directorio,
        segmento=segmento,
    )
    esperado = vectores[int(fila)]
    if tolerancia == 0:
        iguales = bool(np.array_equal(consulta, esperado))
    else:
        iguales = bool(np.allclose(consulta, esperado, atol=tolerancia, rtol=0))
    return {
        "iguales": iguales,
        "fila": int(fila),
        "id": oid,
        "max_diferencia": float(np.max(np.abs(consulta - esperado))),
    }
