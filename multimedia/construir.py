import argparse
import csv
import json
from pathlib import Path

from . import bovw, cache, codebook, config, histogramas


def _numero(valor):
    if isinstance(valor, (int, float)):
        return valor
    texto = str(valor).strip()
    try:
        return int(texto)
    except ValueError:
        pass
    try:
        return float(texto)
    except ValueError:
        return texto


def leer_parametros(pares) -> dict:
    params = {}
    for par in pares or []:
        if "=" not in par:
            raise ValueError(f"--param espera clave=valor, se dio {par!r}")
        clave, valor = par.split("=", 1)
        clave = clave.strip()
        if not clave:
            raise ValueError(f"--param sin nombre de parametro: {par!r}")
        params[clave] = _numero(valor)
    return params


def cargar_objetos_archivo(ruta) -> list[tuple]:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"no existe la lista de objetos: {ruta}")

    if ruta.suffix.lower() == ".json":
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, list):
            raise ValueError(f"{ruta} debe contener una lista de objetos")
        return [(d["id"], d["ruta"]) for d in datos]

    objetos = []
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        lector = csv.reader(f)
        for numero_fila, fila in enumerate(lector, start=1):
            if not fila or all(not c.strip() for c in fila):
                continue
            if len(fila) < 2:
                raise ValueError(
                    f"{ruta}:{numero_fila}: se esperaban dos columnas id,ruta"
                )
            oid, ruta_obj = fila[0].strip(), fila[1].strip()
            if numero_fila == 1 and oid.lower() in ("id", "objeto"):
                continue
            objetos.append((oid, ruta_obj))
    if not objetos:
        raise ValueError(f"{ruta} no contiene objetos")
    return objetos


def cargar_ids_entrenamiento(ruta) -> list:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"no existe la lista de entrenamiento: {ruta}")

    if ruta.suffix.lower() == ".json":
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, list):
            raise ValueError(f"{ruta} debe contener una lista de ids")
        salida = []
        for entrada in datos:
            if isinstance(entrada, dict):
                if "id" not in entrada:
                    raise ValueError(f"{ruta}: cada objeto necesita una clave 'id'")
                salida.append(entrada["id"])
            else:
                salida.append(entrada)
        return salida

    ids = []
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        lector = csv.reader(f)
        for numero_fila, fila in enumerate(lector, start=1):
            if not fila or all(not c.strip() for c in fila):
                continue
            valor = fila[0].strip()
            if numero_fila == 1 and valor.lower() in ("id", "objeto"):
                continue
            if valor:
                ids.append(valor)
    if not ids:
        raise ValueError(f"{ruta} no contiene ids de entrenamiento")
    return ids


def tamanos(texto) -> list[int]:
    valores = []
    for parte in str(texto).split(","):
        parte = parte.strip().replace("_", "")
        if not parte:
            continue
        valor = int(parte)
        if valor <= 0:
            raise ValueError("--n debe ser positivo")
        valores.append(valor)
    if not valores:
        raise ValueError("--n no contiene ningun tamano")
    return valores


def k_guardado(tipo: str, base=None) -> int | None:
    ruta = Path(base or config.BASE) / "barrido_k" / "k_elegido.json"
    if not ruta.exists():
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        entrada = datos.get(tipo, {})
        valor = entrada.get("K")
        return int(valor) if valor is not None else None
    except (OSError, ValueError, TypeError):
        return None


def construir(tipo: str, objetos=None, *, tamanos_coleccion=(100_000,),
              k: int | None = None, n_entrenamiento: int | None = None,
              ids_entrenamiento=None, base=None,
              muestra: int = config.MUESTRA_KMEANS,
              semilla: int = config.SEMILLA, workers: int | None = None,
              shard: int = config.SHARD, forzar: bool = False,
              compactar_cache: bool = False, podar: bool = False,
              reintentar_errores: bool = False,
              params: dict | None = None) -> dict:

    tipo = config.validar_tipo(tipo)
    base = Path(base) if base is not None else None
    modelo_dir = config.directorio_modelo(tipo, base)
    cache_dir = modelo_dir / "cache"
    params = dict(params or {})

    resumen_cache = None
    if objetos is not None:
        resumen_cache = cache.sincronizar(
            tipo, objetos, directorio=cache_dir, shard=shard, workers=workers,
            reintentar_errores=reintentar_errores,
            eliminar_ausentes=podar,
            **{**config.parametros(tipo), **params},
        )

    if compactar_cache:
        compactacion = cache.compactar(
            tipo, directorio=cache_dir, shard=shard, forzar=True,
        )
        print(
            f"[{tipo}] compactacion manual: {compactacion['shards']} shards, "
            f"{compactacion['descriptores']} descriptores vigentes",
            flush=True,
        )

    n_cache = cache.contar_objetos(tipo, directorio=cache_dir)
    if n_cache == 0:
        raise ValueError(
            f"la cache de {cache_dir} esta vacia; pase --objetos con la lista "
            "de archivos (CSV id,ruta o JSON)"
        )

    if k is None:
        k = k_guardado(tipo, base)
    K = int(k or config.k_por_defecto(tipo))

    if ids_entrenamiento is not None:
        ids_entrenamiento = list(ids_entrenamiento)
        n_entrenamiento = None

    meta_previo = {}
    if (modelo_dir / "meta.json").exists():
        try:
            meta_previo = codebook.cargar_meta(tipo, directorio=modelo_dir)
        except (OSError, ValueError):
            meta_previo = {}

    print(
        f"[{tipo}] codebook: K={K}, cache={n_cache}, "
        f"entrenamiento={'ids explicitos' if ids_entrenamiento is not None else n_entrenamiento or 'toda la cache'}",
        flush=True,
    )
    codebook.entrenar_codebook(
        tipo, K=K, base=base, directorio=modelo_dir, cache_dir=cache_dir,
        ids_entrenamiento=ids_entrenamiento,
        n_entrenamiento=n_entrenamiento,
        muestra=muestra, semilla=semilla, forzar=forzar, params=params,
    )
    meta = codebook.cargar_meta(tipo, directorio=modelo_dir)
    reutilizado_codebook = (
        not forzar
        and meta_previo.get("huella_entrenamiento") == meta.get("huella_entrenamiento")
        and meta_previo.get("huella_codebook") == meta.get("huella_codebook")
    )
    print(
        f"[{tipo}] codebook {'reutilizado' if reutilizado_codebook else 'entrenado'}: "
        f"huella={meta['huella_codebook'][:12]}",
        flush=True,
    )

    if objetos is not None:
        # La coleccion sale de la lista recibida (en su orden), no de todo el
        # manifiesto: una prueba con 100 objetos no debe tocar las de 100k.
        vigentes = {
            cache.clave_id(v)
            for v in cache.fuentes(tipo, directorio=cache_dir)
        }
        pedidos = [
            oid for oid, _ in objetos if cache.clave_id(oid) in vigentes
        ]
        disponibles = cache.expandir_ids(
            tipo, pedidos, directorio=cache_dir,
        ) if pedidos else []
    else:
        disponibles = cache.ids_objetos(tipo, directorio=cache_dir)
    colecciones = []
    for N in tamanos_coleccion:
        N = int(N)
        if N > len(disponibles):
            raise ValueError(
                f"la coleccion de {N} no cabe en la lista de {len(disponibles)} "
                "objetos vigentes; pase una lista --objetos mas grande"
            )
        ids_n = disponibles[:N]
        print(f"[{tipo}] construyendo coleccion N={N}", flush=True)

        hist = histogramas.actualizar_histogramas(
            tipo, ids_n, base=base, directorio=modelo_dir,
            cache_dir=cache_dir, forzar=forzar,
        )
        resumen = bovw.construir_coleccion(
            tipo, N, base=base, ids=ids_n, K=K, directorio=modelo_dir,
            cache_dir=cache_dir, forzar=forzar, params=params,
        )
        resumen["histogramas"] = {
            "agregados": hist["agregados"],
            "cambiados": hist["cambiados"],
            "reutilizados": hist["reutilizados"],
        }
        print(
            f"[{tipo}] N={N}: {resumen['K']} palabras, "
            f"reutilizado={resumen.get('reutilizado', False)}, "
            f"histogramas={hist['agregados']} nuevos/"
            f"{hist['cambiados']} cambiados/{hist['reutilizados']} reutilizados, "
            f"vectores={resumen['vectores']}",
            flush=True,
        )
        colecciones.append(resumen)

    return {
        "tipo": tipo,
        "K": K,
        "n_entrenamiento": int(meta.get("n_entrenamiento", 0)),
        "codebook_reutilizado": reutilizado_codebook,
        "huella_codebook": meta.get("huella_codebook"),
        "cache_objetos": n_cache,
        "cache": resumen_cache,
        "colecciones": colecciones,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Construye cache, codebook y colecciones multimedia (E4)",
    )
    parser.add_argument("--tipo", choices=("imagen", "audio"), required=True)
    parser.add_argument(
        "--objetos", default=None,
        help="CSV id,ruta o JSON [{'id','ruta'}] con los archivos a extraer",
    )
    parser.add_argument(
        "--n", default="100000",
        help="tamanos de coleccion separados por coma (por defecto 100000)",
    )
    parser.add_argument(
        "--k", type=int, default=None,
        help="palabras del codebook; si se omite usa barrido_k/k_elegido.json "
             "y, en su defecto, config.k_por_defecto(tipo)",
    )
    parser.add_argument(
        "--n-entrenamiento", type=int, default=None,
        help="objetos de la cache para entrenar el vocabulario (por defecto, todos)",
    )
    parser.add_argument(
        "--entrenamiento", default=None,
        help="CSV o JSON con los ids exactos de entrenamiento (sustituye a "
             "--n-entrenamiento)",
    )
    parser.add_argument("--muestra", type=int, default=config.MUESTRA_KMEANS,
                        help="descriptores para K-Means")
    parser.add_argument("--workers", type=int, default=None,
                        help="procesos de extraccion; en Windows use >= 2 con este script")
    parser.add_argument("--shard", type=int, default=config.SHARD,
                        help="objetos por archivo de cache")
    parser.add_argument("--base", default=None,
                        help="carpeta de artefactos (por defecto config.BASE)")
    parser.add_argument("--param", action="append", default=[],
                        metavar="CLAVE=VALOR",
                        help="parametro de extraccion, repetible")
    parser.add_argument("--forzar", action="store_true",
                        help="recalcula codebook, histogramas y colecciones")
    parser.add_argument("--compactar", action="store_true",
                        help="reescribe los shards dejando solo lo vigente")
    parser.add_argument("--reintentar-errores", action="store_true",
                        help="vuelve a procesar los archivos con estado 'error'")
    parser.add_argument("--podar", action="store_true",
                        help="marca como eliminados los objetos que no esten en "
                             "--objetos; sus descriptores se borran en la proxima "
                             "compactacion")
    args = parser.parse_args(argv)

    objetos = None
    if args.objetos:
        objetos = cargar_objetos_archivo(args.objetos)

    ids_entrenamiento = None
    if args.entrenamiento:
        ids_entrenamiento = cargar_ids_entrenamiento(args.entrenamiento)

    resumen = construir(
        args.tipo, objetos, tamanos_coleccion=tamanos(args.n), k=args.k,
        n_entrenamiento=args.n_entrenamiento,
        ids_entrenamiento=ids_entrenamiento,
        base=args.base, muestra=args.muestra,
        workers=args.workers, shard=args.shard, forzar=args.forzar,
        compactar_cache=args.compactar,
        reintentar_errores=args.reintentar_errores,
        podar=args.podar,
        params=leer_parametros(args.param),
    )
    print(json.dumps(resumen, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import multiprocessing as mp

    mp.freeze_support()
    raise SystemExit(main())
