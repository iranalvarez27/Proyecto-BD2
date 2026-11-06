import hashlib
import json
import multiprocessing as mp
import os
import time
import zipfile
from pathlib import Path

import numpy as np
import numpy.lib.format as npformat

from . import config
from .mfcc import cargar_audio, extraer_mfcc, segmentar
from .sift import extraer_sift

PATRON_SHARD = "parte_*.npz"
NOMBRE_MANIFIESTO = "manifiesto.json"
NOMBRE_CACHE = "cache.json"
NOMBRE_ERRORES = "errores.log"
_BLOQUE_HUELLA = 1 << 20


# ---------------------------------------------------------------------------
# Identificadores
# ---------------------------------------------------------------------------
def _id_segmento(track_id, segmento: int):
    if isinstance(track_id, tuple):
        return track_id + (segmento,)
    return (track_id, segmento)


def normalizar_id(valor):
    if isinstance(valor, np.ndarray):
        if valor.ndim == 0:
            return normalizar_id(valor.item())
        return tuple(normalizar_id(v) for v in valor.tolist())
    if isinstance(valor, np.generic):
        return valor.item()
    return valor


_normalizar_id = normalizar_id


def crear_array_ids(ids):
    arr = np.empty(len(ids), dtype=object)
    arr[:] = list(ids)
    return arr


# Compatibilidad interna.
_array_ids = crear_array_ids


def clave_id(valor) -> str:
    valor = normalizar_id(valor)
    if isinstance(valor, str):
        return valor
    if isinstance(valor, (int, float, bool)) or valor is None:
        return str(valor)
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id_de_json(valor):
    if isinstance(valor, list):
        return tuple(_id_de_json(v) for v in valor)
    return normalizar_id(valor)


def _id_a_json(valor):
    valor = normalizar_id(valor)
    if isinstance(valor, tuple):
        return [_id_a_json(v) for v in valor]
    if isinstance(valor, np.generic):
        return valor.item()
    return valor


# ---------------------------------------------------------------------------
# Huella de archivo
# ---------------------------------------------------------------------------
def _datos_archivo(ruta) -> dict:
    st = Path(ruta).stat()
    return {"tamano": int(st.st_size), "mtime_ns": int(st.st_mtime_ns)}


def huella_archivo(ruta, previa=None) -> str:
    ruta = Path(ruta)
    datos = _datos_archivo(ruta)
    if previa:
        try:
            mismo_tamano = int(previa.get("tamano", -1)) == datos["tamano"]
            mismo_mtime = int(previa.get("mtime_ns", -1)) == datos["mtime_ns"]
        except (TypeError, ValueError):
            mismo_tamano = mismo_mtime = False
        if mismo_tamano and mismo_mtime and previa.get("huella_archivo"):
            return previa["huella_archivo"]

    h = hashlib.sha1()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(_BLOQUE_HUELLA), b""):
            h.update(bloque)
    return h.hexdigest()


def _estado_archivo(ruta, previa=None) -> dict:
    try:
        datos = _datos_archivo(ruta)
        huella = huella_archivo(ruta, previa)
    except OSError:
        return {"tamano": None, "mtime_ns": None, "huella_archivo": None}
    return {**datos, "huella_archivo": huella}


# ---------------------------------------------------------------------------
# Extraccion de un objeto (se ejecuta en los procesos trabajadores)
# ---------------------------------------------------------------------------

def _procesar_item(tarea):
    tipo, item, params, cortar_audio = tarea
    oid, ruta = item

    try:
        if tipo == "imagen":
            desc = extraer_sift(ruta, params["max_lado"], params["nfeatures"])
            return oid, [(oid, desc)], None

        if cortar_audio:
            segmentos = segmentar(ruta, params["sr"], params["seg_s"])
            salida = [
                (_id_segmento(oid, j), extraer_mfcc(
                    segmento,
                    sr=params["sr"],
                    n_fft=params["n_fft"],
                    hop=params["hop"],
                    n_mfcc=params["n_mfcc"],
                ))
                for j, segmento in enumerate(segmentos)
            ]
        else:
            y = cargar_audio(ruta, params["sr"])
            salida = [(oid, extraer_mfcc(
                y,
                sr=params["sr"],
                n_fft=params["n_fft"],
                hop=params["hop"],
                n_mfcc=params["n_mfcc"],
            ))]

        return oid, salida, None
    except Exception as ex:  # un mp3 corrupto no debe detener todo el proceso
        return oid, [], f"{oid}\t{ruta}\t{type(ex).__name__}: {ex}"


# ---------------------------------------------------------------------------
# Shards
# ---------------------------------------------------------------------------
def _nombre_shard(indice: int) -> str:
    return f"parte_{indice:04d}.npz"


def _ruta_shard(directorio: Path, indice: int) -> Path:
    return Path(directorio) / _nombre_shard(indice)


def _indices_shards(directorio: Path) -> list[int]:
    directorio = Path(directorio)
    if not directorio.exists():
        return []
    indices = []
    for ruta in directorio.glob(PATRON_SHARD):
        tallo = ruta.stem  # parte_0000
        try:
            indices.append(int(tallo.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return sorted(indices)


def _forma_desc(ruta: Path) -> tuple[int, ...] | None:
    with zipfile.ZipFile(ruta) as z:
        nombre = next(
            (n for n in z.namelist() if n.endswith("desc.npy")), None
        )
        if nombre is None:
            return None
        with z.open(nombre) as f:
            version = npformat.read_magic(f)
            if version == (1, 0):
                forma, _, _ = npformat.read_array_header_1_0(f)
            elif version == (2, 0):
                forma, _, _ = npformat.read_array_header_2_0(f)
            else:
                forma, _, _ = npformat._read_array_header(f, version)
            return tuple(forma)


def _shard_valido(ruta: Path, dimension: int) -> bool:
    try:
        forma = _forma_desc(ruta)
        if forma is None or len(forma) != 2 or forma[1] != dimension:
            return False
        with np.load(ruta, allow_pickle=True) as z:
            ids = z["ids"]
            offsets = z["offsets"]
        return (
            offsets.ndim == 1
            and len(offsets) == len(ids) + 1
            and offsets[0] == 0
            and offsets[-1] == forma[0]
            and np.all(np.diff(offsets) >= 0)
        )
    except Exception:
        return False


def _escribir_shard(directorio: Path, indice: int, ids, descs, dimension: int) -> None:
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)

    if descs:
        desc = np.concatenate(descs, axis=0)
    else:
        dtype = np.uint8 if dimension == config.DIM_IMAGEN else np.float32
        desc = np.empty((0, dimension), dtype=dtype)

    offsets = np.zeros(len(ids) + 1, dtype=np.int64)
    if descs:
        offsets[1:] = np.cumsum([len(d) for d in descs], dtype=np.int64)

    destino = _ruta_shard(directorio, indice)
    temporal = directorio / f"{destino.stem}.tmp.npz"
    np.savez(temporal, ids=_array_ids(ids), offsets=offsets, desc=desc)
    os.replace(temporal, destino)


def _leer_shard(ruta: Path):
    with np.load(ruta, allow_pickle=True) as z:
        return z["ids"], z["offsets"], z["desc"]


# ---------------------------------------------------------------------------
# Manifiesto y cache.json
# ---------------------------------------------------------------------------
def _escribir_json_atomico(ruta, datos, compacto: bool = False) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        if compacto:
            json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)


def _leer_json(ruta) -> dict:
    ruta = Path(ruta)
    if not ruta.exists():
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _leer_cache_json(directorio: Path) -> dict:
    return _leer_json(Path(directorio) / NOMBRE_CACHE)


def resumen_cache(tipo: str, base=None, directorio=None) -> dict:
    config.validar_tipo(tipo)
    directorio = Path(directorio) if directorio is not None else config.directorio_cache(tipo, base)
    return _leer_cache_json(directorio)


def manifiesto(tipo: str, base=None, directorio=None) -> dict:
    config.validar_tipo(tipo)
    directorio = Path(directorio) if directorio is not None else config.directorio_cache(tipo, base)
    return _leer_json(Path(directorio) / NOMBRE_MANIFIESTO)


def _abrir_cache(directorio: Path, tipo: str, parametros: dict, shard: int) -> dict:
    directorio = Path(directorio)
    info = _leer_cache_json(directorio)
    shards = _indices_shards(directorio)
    hay_manifiesto = (directorio / NOMBRE_MANIFIESTO).exists()

    if shards and not hay_manifiesto:
        raise ValueError(
            f"cache de version 1 en {directorio}: no tiene {NOMBRE_MANIFIESTO}. "
            "Borrila y ejecute construir.py de nuevo (no hay migracion)."
        )
    if info:
        if int(info.get("version", 0)) != config.VERSION_CACHE:
            raise ValueError(
                f"cache de version {info.get('version')} en {directorio}; "
                f"se esperaba {config.VERSION_CACHE}. Borrila y vuelva a construirla."
            )
        if info.get("tipo") != tipo:
            raise ValueError(
                f"la cache de {directorio} es de tipo {info.get('tipo')!r}, no {tipo!r}"
            )
        if info.get("shard") != shard and int(info.get("shards", 0)) > 0:
            raise ValueError(
                f"la cache existente uso shard={info.get('shard')}, "
                f"no se puede reanudar con shard={shard}; use otra carpeta o borrela"
            )
        if info.get("params") and info["params"] != parametros:
            raise ValueError(
                "los parametros de extraccion no coinciden con la cache existente; "
                "use otra carpeta o borre la cache"
            )
    return info


# ---------------------------------------------------------------------------
# Indices sobre el manifiesto
# ---------------------------------------------------------------------------
def _indice_objetos(manif: dict) -> dict:
    indice = {}
    for entrada in manif.values():
        if entrada.get("estado") != "ok":
            continue
        for obj in entrada.get("objetos", []):
            oid = _id_de_json(obj["id"])
            indice[clave_id(oid)] = (
                int(obj["shard"]), int(obj["pos"]), oid,
            )
    return indice


def _ids_de_entrada(entrada: dict) -> list:
    return [_id_de_json(obj["id"]) for obj in entrada.get("objetos", [])]


def ids_objetos(tipo: str, base=None, directorio=None) -> list:
    manif = manifiesto(tipo, base=base, directorio=directorio)
    ids = []
    for entrada in manif.values():
        if entrada.get("estado") != "ok":
            continue
        ids.extend(_ids_de_entrada(entrada))
    return ids


def fuentes(tipo: str, base=None, directorio=None) -> list:
    manif = manifiesto(tipo, base=base, directorio=directorio)
    return [
        _id_de_json(e.get("id_fuente", clave))
        for clave, e in manif.items() if e.get("estado") == "ok"
    ]


def rutas(tipo: str, base=None, directorio=None) -> list[tuple]:
    manif = manifiesto(tipo, base=base, directorio=directorio)
    return [
        (_id_de_json(e.get("id_fuente", clave)), e.get("ruta"))
        for clave, e in manif.items() if e.get("estado") == "ok"
    ]


def expandir_ids(tipo: str, ids, base=None, directorio=None) -> list:
    manif = manifiesto(tipo, base=base, directorio=directorio)
    indice = _indice_objetos(manif)
    salida = []
    vistos = set()
    for valor in ids:
        clave = clave_id(valor)
        if clave in indice:
            oid = indice[clave][2]
            candidatos = [oid]
        elif clave in manif and manif[clave].get("estado") == "ok":
            candidatos = _ids_de_entrada(manif[clave])
        else:
            raise KeyError(f"el id {valor!r} no esta en la cache como objeto ni como fuente")
        for oid in candidatos:
            c = clave_id(oid)
            if c not in vistos:
                vistos.add(c)
                salida.append(oid)
    return salida


def huellas_de_ids(tipo: str, ids, base=None, directorio=None) -> list[str]:
    manif = manifiesto(tipo, base=base, directorio=directorio)
    por_objeto = {}
    for entrada in manif.values():
        if entrada.get("estado") != "ok":
            continue
        huella = entrada.get("huella_archivo")
        for obj in entrada.get("objetos", []):
            por_objeto[clave_id(_id_de_json(obj["id"]))] = huella

    salida = []
    for oid in ids:
        clave = clave_id(oid)
        if clave not in por_objeto:
            raise KeyError(f"el objeto {oid!r} no esta en la cache (o esta eliminado)")
        huella = por_objeto[clave]
        if not huella:
            raise ValueError(f"la entrada de {oid!r} no tiene huella_archivo")
        salida.append(huella)
    return salida


# ---------------------------------------------------------------------------
# Lectura de descriptores
# ---------------------------------------------------------------------------
def _grupos_por_shard(tipo: str, ids, directorio: Path) -> dict[int, list[tuple[int, object]]]:
    manif = _leer_json(Path(directorio) / NOMBRE_MANIFIESTO)
    indice = _indice_objetos(manif)
    grupos: dict[int, list[tuple[int, object]]] = {}
    for oid in ids:
        clave = clave_id(oid)
        if clave not in indice:
            raise KeyError(f"el objeto {oid!r} no esta en la cache (o esta eliminado)")
        shard, pos, oid_real = indice[clave]
        grupos.setdefault(shard, []).append((pos, oid_real))
    return grupos


def _leer_grupos(directorio: Path, grupos: dict[int, list[tuple[int, object]]]):
    for shard in sorted(grupos):
        ruta = _ruta_shard(directorio, shard)
        ids_shard, offsets, desc = _leer_shard(ruta)
        for pos, oid in grupos[shard]:
            real = _normalizar_id(ids_shard[pos])
            if clave_id(real) != clave_id(oid):
                raise ValueError(
                    f"el manifiesto no coincide con {ruta.name} en la posicion {pos}: "
                    f"dice {oid!r} y el shard tiene {real!r}. Reconstruya la cache."
                )
            yield oid, desc[offsets[pos]:offsets[pos + 1]]


def iterar(tipo: str, ids=None, base=None, directorio=None):
    config.validar_tipo(tipo)
    directorio = Path(directorio) if directorio is not None else config.directorio_cache(tipo, base)
    if ids is None:
        ids = ids_objetos(tipo, directorio=directorio)
    grupos = _grupos_por_shard(tipo, list(ids), directorio)
    yield from _leer_grupos(directorio, grupos)


# Compatibilidad con el nombre anterior.
iterar_cache = iterar


def leer_descriptores(tipo: str, ids, base=None, directorio=None) -> list[tuple]:
    config.validar_tipo(tipo)
    directorio = Path(directorio) if directorio is not None else config.directorio_cache(tipo, base)
    ids = list(ids)
    grupos = _grupos_por_shard(tipo, ids, directorio)
    encontrados = {}
    for oid, desc in _leer_grupos(directorio, grupos):
        encontrados[clave_id(oid)] = desc
    return [(normalizar_id(oid), encontrados[clave_id(oid)]) for oid in ids]


# ---------------------------------------------------------------------------
# Sincronizacion
# ---------------------------------------------------------------------------
def _descriptores_fisicos(directorio: Path) -> int:
    total = 0
    for indice in _indices_shards(directorio):
        try:
            with np.load(_ruta_shard(directorio, indice), allow_pickle=True) as z:
                total += int(z["offsets"][-1])
        except Exception:
            continue
    return total


def _descriptores_vigentes(manif: dict) -> int:
    return sum(
        int(obj.get("n_desc", 0))
        for entrada in manif.values() if entrada.get("estado") == "ok"
        for obj in entrada.get("objetos", [])
    )


def _huella_cache(manif: dict, parametros: dict) -> str:
    h = hashlib.sha1()
    h.update(json.dumps(parametros, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for clave in sorted(manif):
        entrada = manif[clave]
        if entrada.get("estado") != "ok":
            continue
        h.update(f"\n{clave}\t{entrada.get('huella_archivo')}".encode("utf-8"))
    return h.hexdigest()


def _entrada_ok(id_fuente, ruta, estado_archivo: dict, salida, shard: int,
                pos_inicial: int) -> dict:
    objetos = []
    pos = pos_inicial
    for id_objeto, desc in salida:
        objetos.append({
            "id": _id_a_json(id_objeto),
            "shard": int(shard),
            "pos": int(pos),
            "n_desc": int(len(desc)),
        })
        pos += 1
    return {
        "id_fuente": _id_a_json(id_fuente),
        "ruta": str(ruta),
        **estado_archivo,
        "estado": "ok",
        "objetos": objetos,
    }


def _entrada_error(id_fuente, ruta, estado_archivo: dict, error: str) -> dict:
    return {
        "id_fuente": _id_a_json(id_fuente),
        "ruta": str(ruta),
        **estado_archivo,
        "estado": "error",
        "error": error,
        "objetos": [],
    }


def _registrar_error(directorio: Path, error: str) -> None:
    with open(Path(directorio) / NOMBRE_ERRORES, "a", encoding="utf-8") as f:
        f.write(error + "\n")


def _trabajadores(workers: int | None) -> int:
    if workers is None:
        # En Windows el arranque por spawn reimporta el script principal; si
        # no tiene guardia `if __name__ == "__main__"` los procesos fallan.
        trabajadores = 1 if os.name == "nt" else min(4, os.cpu_count() or 1)
    else:
        trabajadores = workers
    return max(1, int(trabajadores))


def _resumen(directorio: Path, tipo: str, shard: int, parametros: dict, manif: dict,
             **extra) -> dict:
    fisicos = _descriptores_fisicos(directorio)
    vigentes = _descriptores_vigentes(manif)
    resumen = {
        "tipo": tipo,
        "version": config.VERSION_CACHE,
        "shard": shard,
        "objetos": len(ids_objetos(tipo, directorio=directorio)),
        "shards": len(_indices_shards(directorio)),
        "descriptores": vigentes,
        "fisicos": fisicos,
        "obsoletos": max(0, fisicos - vigentes),
        "params": parametros,
        "huella_cache": _huella_cache(manif, parametros),
        **extra,
    }
    return resumen


def sincronizar(tipo: str, objetos, base=None, directorio=None, *,
                shard: int = config.SHARD, workers: int | None = None,
                cortar_audio: bool = True, reintentar_errores: bool = False,
                eliminar_ausentes: bool = False,
                compactar_auto: bool = True,
                umbral_compactar: float = config.UMBRAL_COMPACTAR,
                **params) -> dict:
    
    tipo = config.validar_tipo(tipo)
    if shard <= 0:
        raise ValueError("shard debe ser positivo")
    if not 0 <= float(umbral_compactar) <= 1:
        raise ValueError("umbral_compactar debe estar entre 0 y 1")
    if workers is not None and int(workers) < 1:
        raise ValueError("workers debe ser positivo")

    directorio = Path(directorio) if directorio is not None else config.directorio_cache(tipo, base)
    directorio.mkdir(parents=True, exist_ok=True)

    parametros = {**config.parametros(tipo), **params}
    _abrir_cache(directorio, tipo, parametros, shard)
    manif = _leer_json(directorio / NOMBRE_MANIFIESTO)

    lista = list(objetos)
    vistos = {}
    for oid, ruta in lista:
        clave = clave_id(oid)
        if clave in vistos:
            raise ValueError(f"id duplicado en la lista de objetos: {oid!r}")
        vistos[clave] = (oid, ruta)

    pendientes = []
    iguales = 0
    errores_previos = 0
    nuevos = 0
    cambiados = 0
    shards_existentes = set(_indices_shards(directorio))

    for clave, (oid, ruta) in vistos.items():
        previa = manif.get(clave)
        estado = _estado_archivo(ruta, previa)
        huella = estado.get("huella_archivo")

        if previa and previa.get("estado") == "ok" and huella \
                and previa.get("huella_archivo") == huella:
            # Si falta el shard (por ejemplo, se borro a mano o se perdio en
            # una copia), hay que reextraer aunque el archivo no cambio.
            shards_entrada = {
                int(obj["shard"]) for obj in previa.get("objetos", [])
                if "shard" in obj
            }
            if shards_entrada.issubset(shards_existentes):
                iguales += 1
                # Actualizar la ruta o el mtime no cambia el contenido: los
                # descriptores siguen siendo validos.
                previa["ruta"] = str(ruta)
                previa["tamano"] = estado["tamano"]
                previa["mtime_ns"] = estado["mtime_ns"]
                continue

        if previa and previa.get("estado") == "error" and not reintentar_errores:
            misma = (
                previa.get("huella_archivo") == huella
                and previa.get("tamano") == estado.get("tamano")
                and previa.get("mtime_ns") == estado.get("mtime_ns")
            )
            if misma:
                errores_previos += 1
                continue

        if previa is None or previa.get("estado") == "eliminado":
            nuevos += 1
        elif previa.get("estado") == "ok":
            cambiados += 1
        pendientes.append((clave, oid, ruta, estado))

    eliminados = 0
    if eliminar_ausentes:
        for clave, entrada in manif.items():
            if clave in vistos:
                continue
            if entrada.get("estado") != "eliminado":
                entrada["estado"] = "eliminado"
                eliminados += 1

    errores = 0
    inicio_tiempo = time.time()
    trabajadores = _trabajadores(workers)
    dimension = config.dimension(tipo)

    inicio_shard = (max(_indices_shards(directorio), default=-1) + 1)
    escritos = 0
    desde_checkpoint = 0
    pool = mp.Pool(processes=trabajadores) if trabajadores > 1 else None

    try:
        for desde in range(0, len(pendientes), shard):
            lote = pendientes[desde:desde + shard]
            tareas = [(tipo, (oid, ruta), parametros, cortar_audio) for _, oid, ruta, _ in lote]
            if pool is None:
                resultados = [_procesar_item(t) for t in tareas]
            else:
                resultados = pool.imap(_procesar_item, tareas)

            shard_destino = inicio_shard + escritos
            ids, descs = [], []
            entradas_lote = {}
            for (clave, oid, ruta, estado), (id_fuente, salida, error) in zip(lote, resultados):
                if error:
                    errores += 1
                    entradas_lote[clave] = _entrada_error(id_fuente, ruta, estado, error)
                    _registrar_error(directorio, error)
                    continue
                entradas_lote[clave] = _entrada_ok(
                    id_fuente, ruta, estado, salida, shard_destino, len(ids),
                )
                for id_objeto, desc in salida:
                    ids.append(id_objeto)
                    descs.append(desc)

            # 1) primero los datos: el manifiesto solo puede apuntar a un shard
            # completo en disco (regla de write-ahead logging, 9.2.3).
            if ids:
                _escribir_shard(directorio, shard_destino, ids, descs, dimension)
                escritos += 1
                print(
                    f"[{tipo}] shard {shard_destino}: {len(ids)} objetos "
                    f"({len(pendientes) - min(len(pendientes), desde + len(lote))} pendientes)",
                    flush=True,
                )
            # 2) despues el puntero, en memoria.
            manif.update(entradas_lote)

            # 3) checkpoint cada MANIFIESTO_CADA shards (P3 nivel 2).
            desde_checkpoint += 1
            if desde_checkpoint >= config.MANIFIESTO_CADA:
                _escribir_json_atomico(
                    directorio / NOMBRE_MANIFIESTO, manif, compacto=True,
                )
                desde_checkpoint = 0
    finally:
        if pool is not None:
            pool.close()
            pool.join()
        # Seguro aunque haya habido una excepcion: manif solo contiene lotes
        # cuyo shard ya esta completo en disco.
        _escribir_json_atomico(
            directorio / NOMBRE_MANIFIESTO, manif, compacto=True,
        )

    resumen = _resumen(
        directorio, tipo, shard, parametros, manif,
        iguales=iguales, nuevos=nuevos, cambiados=cambiados,
        eliminados=eliminados, errores=errores, errores_previos=errores_previos,
        segundos=round(time.time() - inicio_tiempo, 3),
        compactado=False,
    )
    _escribir_json_atomico(directorio / NOMBRE_CACHE, resumen)

    if compactar_auto and resumen["fisicos"] > 0:
        comp = compactar(
            tipo, directorio=directorio, umbral=umbral_compactar,
            shard=shard, forzar=False,
        )
        resumen["compactado"] = bool(comp.get("compactado"))
        if comp.get("compactado"):
            resumen.update({
                k: comp[k] for k in ("shards", "descriptores", "fisicos", "obsoletos")
                if k in comp
            })
            resumen["huella_cache"] = _huella_cache(
                _leer_json(directorio / NOMBRE_MANIFIESTO), parametros,
            )
            _escribir_json_atomico(directorio / NOMBRE_CACHE, resumen)

    return resumen


# Alias con el nombre historico: ahora la reanudacion es por id, no por posicion.
def construir_cache(tipo: str, objetos, base=None, directorio=None, **kwargs) -> dict:
    kwargs.pop("reanudar", None)  # ya no existe: sincronizar siempre reutiliza
    return sincronizar(tipo, objetos, base=base, directorio=directorio, **kwargs)


# ---------------------------------------------------------------------------
# Compactacion
# ---------------------------------------------------------------------------
def _shards_referenciados(manif: dict) -> set[int]:
    referenciados = set()
    for entrada in manif.values():
        for obj in entrada.get("objetos", []):
            try:
                referenciados.add(int(obj["shard"]))
            except (KeyError, TypeError, ValueError):
                continue
    return referenciados


def _limpiar_huerfanos(directorio: Path, manif: dict) -> int:
    referenciados = _shards_referenciados(manif)
    borrados = 0
    for indice in _indices_shards(directorio):
        if indice in referenciados:
            continue
        try:
            _ruta_shard(directorio, indice).unlink()
            borrados += 1
        except OSError:
            pass
    return borrados


def compactar(tipo: str, base=None, directorio=None, *,
              umbral: float = config.UMBRAL_COMPACTAR,
              shard: int | None = None, forzar: bool = False) -> dict:
    tipo = config.validar_tipo(tipo)
    directorio = Path(directorio) if directorio is not None else config.directorio_cache(tipo, base)
    info = _leer_cache_json(directorio)
    shard = int(shard or info.get("shard", config.SHARD))
    parametros = info.get("params") or config.parametros(tipo)

    manif = _leer_json(directorio / NOMBRE_MANIFIESTO)
    fisicos = _descriptores_fisicos(directorio)
    vigentes = _descriptores_vigentes(manif)
    obsoletos = max(0, fisicos - vigentes)
    ratio = (obsoletos / fisicos) if fisicos else 0.0

    resultado = {
        "tipo": tipo,
        "compactado": False,
        "shards": len(_indices_shards(directorio)),
        "descriptores": vigentes,
        "fisicos": fisicos,
        "obsoletos": obsoletos,
        "ratio": ratio,
    }
    if not forzar and (fisicos == 0 or ratio <= float(umbral)):
        return resultado

    dimension = config.dimension(tipo)
    inicio = max(_indices_shards(directorio), default=-1) + 1
    anteriores = _indices_shards(directorio)
    escritos = 0
    fuentes_vigentes = [
        (clave, entrada) for clave, entrada in manif.items()
        if entrada.get("estado") == "ok"
    ]

    # Se leen los descriptores con el manifiesto viejo y se escriben shards
    # nuevos con indices posteriores: si el proceso se cae, la cache anterior
    # sigue siendo valida.
    desde_checkpoint = 0
    for desde in range(0, len(fuentes_vigentes), shard):
        lote = fuentes_vigentes[desde:desde + shard]
        ids_lote = []
        for _, entrada in lote:
            ids_lote.extend(_ids_de_entrada(entrada))

        descs = {
            clave_id(oid): desc
            for oid, desc in leer_descriptores(tipo, ids_lote, directorio=directorio)
        }
        ids, descs_ordenados = [], []
        destino = inicio + escritos
        objetos_por_entrada = []
        for clave, entrada in lote:
            objetos_nuevos = []
            for obj in entrada.get("objetos", []):
                oid = _id_de_json(obj["id"])
                desc = descs[clave_id(oid)]
                objetos_nuevos.append({
                    "id": obj["id"],
                    "shard": int(destino),
                    "pos": len(ids),
                    "n_desc": int(len(desc)),
                })
                ids.append(oid)
                descs_ordenados.append(desc)
            objetos_por_entrada.append((entrada, objetos_nuevos))

        # 1) primero los datos; 2) despues el puntero, solo si el shard quedo
        # completo en disco (misma regla que sincronizar).
        if ids:
            _escribir_shard(directorio, destino, ids, descs_ordenados, dimension)
            escritos += 1
        for entrada, objetos_nuevos in objetos_por_entrada:
            entrada["objetos"] = objetos_nuevos

        desde_checkpoint += 1
        if desde_checkpoint >= config.MANIFIESTO_CADA:
            _escribir_json_atomico(
                directorio / NOMBRE_MANIFIESTO, manif, compacto=True,
            )
            desde_checkpoint = 0

    # Escritura final antes de borrar los shards viejos: el manifiesto ya
    # apunta a los nuevos y ninguno de los viejos se borra antes de tiempo.
    _escribir_json_atomico(
        directorio / NOMBRE_MANIFIESTO, manif, compacto=True,
    )

    # Eliminar los shards viejos solo despues de que el manifiesto apunta a los
    # nuevos. Un shard huerfano de una caida anterior (indice >= inicio) no se
    # toca aqui, pero se ignora porque el manifiesto no lo referencia.
    for indice in anteriores:
        try:
            _ruta_shard(directorio, indice).unlink()
        except OSError:
            pass

    manif = _leer_json(directorio / NOMBRE_MANIFIESTO)
    huerfanos = _limpiar_huerfanos(directorio, manif)
    resumen = _resumen(directorio, tipo, shard, parametros, manif)
    resumen.update({
        "compactado": True, "ratio": ratio, "liberados": obsoletos,
        "huerfanos_limpiados": huerfanos,
    })
    _escribir_json_atomico(directorio / NOMBRE_CACHE, resumen)
    resultado.update(resumen)
    resultado["compactado"] = True
    return resultado


# ---------------------------------------------------------------------------
# Estadisticas
# ---------------------------------------------------------------------------
def contar_objetos(tipo: str, base=None, directorio=None) -> int:
    return len(ids_objetos(tipo, base=base, directorio=directorio))


def contar_descriptores(tipo: str, base=None, directorio=None) -> int:
    manif = manifiesto(tipo, base=base, directorio=directorio)
    return _descriptores_vigentes(manif)
