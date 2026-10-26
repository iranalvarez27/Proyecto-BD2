import argparse
import csv
import gzip
import html
import json
import os
import random
import re
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_RAW = os.path.join(PROJECT_ROOT, "data", "raw")
DIR_SALIDA = os.path.join(PROJECT_ROOT, "data", "amazon")
META = os.path.join(DIR_RAW, "meta_Electronics.jsonl.gz")
RESENAS = os.path.join(DIR_RAW, "Electronics.jsonl.gz")

N_PRODUCTOS = 100_000
MIN_RESENAS = 20
SEMILLA = 42

COLUMNAS_PRODUCTOS = ["id", "asin", "nombre", "descripcion", "caracteristicas", "categoria", "subcategoria",
                      "marca", "precio", "rating", "num_resenas"]
COLUMNAS_IMAGENES = ["producto_id", "asin", "url", "url_alta"]
COLUMNAS_COMPRAS = ["usuario_id", "producto_id", "rating", "timestamp", "compra_verificada"]

_HTML = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")
_CLAVE_ASIN = '"parent_asin": "'


def limpiar(texto) -> str:
    if isinstance(texto, list):
        texto = " ".join(str(t) for t in texto if t)
    texto = html.unescape(_HTML.sub(" ", str(texto or "")))
    return _ESPACIOS.sub(" ", texto).strip()


def imagen_principal(imagenes: list):
    if not imagenes:
        return None
    principal = next((i for i in imagenes if i.get("variant") == "MAIN"), imagenes[0])
    url = principal.get("large") or principal.get("hi_res") or principal.get("thumb")
    if not url:
        return None
    return url, principal.get("hi_res") or url


def producto_completo(item: dict, min_resenas: int):
    precio = item.get("price")
    if not isinstance(precio, (int, float)) or precio <= 0:
        return None
    nombre = limpiar(item.get("title"))
    descripcion = limpiar(item.get("description"))
    caracteristicas = limpiar(item.get("features"))
    imagen = imagen_principal(item.get("images") or [])
    asin = item.get("parent_asin")
    if not asin or not nombre or not (descripcion or caracteristicas) or imagen is None:
        return None
    if (item.get("rating_number") or 0) < min_resenas:
        return None
    categorias = item.get("categories") or []
    detalles = item.get("details") or {}
    categoria = item.get("main_category") or (categorias[1] if len(categorias) > 1 else "")
    if len(categorias) >= 3:
        subcategoria = categorias[2]
    elif categorias:
        subcategoria = categorias[-1]
    else:
        subcategoria = categoria
    return {
        "asin": asin,
        "nombre": nombre,
        "descripcion": descripcion,
        "caracteristicas": caracteristicas,
        "categoria": limpiar(categoria),
        "subcategoria": limpiar(subcategoria),
        "marca": limpiar(detalles.get("Brand") or item.get("store") or ""),
        "precio": round(float(precio), 2),
        "rating": item.get("average_rating") or 0,
        "num_resenas": item.get("rating_number") or 0,
        "url": imagen[0],
        "url_alta": imagen[1],
    }


def elegir_productos(ruta_meta: str, n: int, min_resenas: int, semilla: int) -> tuple:
    azar = random.Random(semilla)
    elegidos = []
    vistos = set()
    leidos = completos = 0
    with gzip.open(ruta_meta, "rt", encoding="utf-8") as f:
        for linea in f:
            leidos += 1
            producto = producto_completo(json.loads(linea), min_resenas)
            if producto is None or producto["asin"] in vistos:
                continue
            vistos.add(producto["asin"])
            completos += 1
            if len(elegidos) < n:
                elegidos.append(producto)
            else:
                j = azar.randrange(completos)
                if j < n:
                    elegidos[j] = producto
    azar.shuffle(elegidos)
    for numero, producto in enumerate(elegidos, start=1):
        producto["id"] = numero
    return elegidos, leidos, completos


def _asin_rapido(linea: str):
    inicio = linea.find(_CLAVE_ASIN)
    if inicio < 0:
        return None
    inicio += len(_CLAVE_ASIN)
    fin = linea.find('"', inicio)
    return linea[inicio:fin] if fin > 0 else None


def extraer_compras(ruta_resenas: str, id_por_asin: dict, ruta_salida: str, progreso: int = 5_000_000) -> tuple:
    usuarios = {}
    compras = leidas = 0
    with gzip.open(ruta_resenas, "rt", encoding="utf-8") as f,             open(ruta_salida, "w", encoding="utf-8", newline="") as salida:
        escritor = csv.writer(salida)
        escritor.writerow(COLUMNAS_COMPRAS)
        for linea in f:
            leidas += 1
            if progreso and leidas % progreso == 0:
                print(f"  {leidas:,} resenas leidas, {compras:,} compras de los productos elegidos", flush=True)
            if _asin_rapido(linea) not in id_por_asin:
                continue
            resena = json.loads(linea)
            producto_id = id_por_asin.get(resena.get("parent_asin"))
            if producto_id is None or not resena.get("user_id"):
                continue
            usuario_id = usuarios.setdefault(resena["user_id"], len(usuarios) + 1)
            escritor.writerow([usuario_id, producto_id, resena.get("rating") or 0, resena.get("timestamp") or 0,
                               bool(resena.get("verified_purchase"))])
            compras += 1
    return compras, leidas, len(usuarios)


def _escribir(ruta: str, columnas: list, filas) -> None:
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(columnas)
        escritor.writerows(filas)


def preparar(ruta_meta: str, ruta_resenas: str | None, salida: str, n: int = N_PRODUCTOS,
             min_resenas: int = MIN_RESENAS, semilla: int = SEMILLA) -> dict:
    os.makedirs(salida, exist_ok=True)
    inicio = time.perf_counter()
    productos, leidos, completos = elegir_productos(ruta_meta, n, min_resenas, semilla)
    if len(productos) < n:
        print(f"aviso: solo hay {len(productos):,} productos completos (se pidieron {n:,})")
    _escribir(os.path.join(salida, "productos.csv"), COLUMNAS_PRODUCTOS,
              ([p[c] for c in COLUMNAS_PRODUCTOS] for p in productos))
    _escribir(os.path.join(salida, "imagenes.csv"), COLUMNAS_IMAGENES,
              ([p["id"], p["asin"], p["url"], p["url_alta"]] for p in productos))
    resumen = {"productos_leidos": leidos, "productos_completos": completos, "productos_elegidos": len(productos),
               "segundos_productos": round(time.perf_counter() - inicio, 1)}
    print(f"{leidos:,} productos leidos, {completos:,} completos, {len(productos):,} elegidos "
          f"({resumen['segundos_productos']}s)", flush=True)

    if ruta_resenas:
        inicio = time.perf_counter()
        compras, leidas, usuarios = extraer_compras(ruta_resenas, {p["asin"]: p["id"] for p in productos},
                                                    os.path.join(salida, "compras.csv"))
        resumen.update({"resenas_leidas": leidas, "compras": compras, "usuarios": usuarios,
                        "segundos_compras": round(time.perf_counter() - inicio, 1)})
        print(f"{leidas:,} resenas leidas, {compras:,} compras de {usuarios:,} usuarios "
              f"({resumen['segundos_compras']}s)")
    return resumen


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Arma el dataset de productos Electronics (Amazon Reviews 2023)")
    parser.add_argument("--meta", default=META)
    parser.add_argument("--resenas", default=RESENAS)
    parser.add_argument("--sin-resenas", action="store_true")
    parser.add_argument("--salida", default=DIR_SALIDA)
    parser.add_argument("-n", type=int, default=N_PRODUCTOS)
    parser.add_argument("--min-resenas", type=int, default=MIN_RESENAS)
    parser.add_argument("--semilla", type=int, default=SEMILLA)
    args = parser.parse_args(argv)
    for ruta in [args.meta] + ([] if args.sin_resenas else [args.resenas]):
        if not os.path.exists(ruta):
            sys.exit(f"no existe '{ruta}': descargalo de https://amazon-reviews-2023.github.io/")
    preparar(args.meta, None if args.sin_resenas else args.resenas, args.salida, args.n, args.min_resenas, args.semilla)


if __name__ == "__main__":
    main()
