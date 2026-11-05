"""Amazon Reviews'23: descarga de imagenes MAIN, subconjuntos 1k/10k/100k y consultas."""
import argparse
import concurrent.futures
import csv
import json
import os
import random
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data import preparar_amazon

CONFIG_PATH = BENCH_DIR / "config.yaml"
DIR_AMAZON_BENCH = BENCH_DIR / "data" / "amazon_img"
DIR_IMGS = DIR_AMAZON_BENCH / "imgs"
DIR_IDS = BENCH_DIR / "datasets" / "ids"
MANIFIESTO_IDS = DIR_IDS / "amazon_img_ids.csv"

URL_META_ELECTRONICS = (
    "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/"
    "meta_categories/meta_Electronics.jsonl.gz"
)


def cargar_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"semilla": 42, "tamanos": [1000, 10000, 100000], "k": 10, "vector": {"consultas": 100}}


def parsear_tamanos(valores) -> list[int]:
    tamanos = []
    for item in valores:
        for parte in str(item).split(","):
            s = parte.strip().lower().replace("_", "")
            if not s:
                continue
            if s.endswith("k"):
                n = int(float(s[:-1]) * 1_000)
            elif s.endswith("m"):
                n = int(float(s[:-1]) * 1_000_000)
            else:
                n = int(s)
            if n <= 0:
                raise ValueError(f"Tamaño inválido: {parte!r}")
            tamanos.append(n)
    if not tamanos:
        raise ValueError("Se debe especificar al menos un tamaño (ej: 1k, 10k, 100k)")
    return sorted(set(tamanos))


def etiqueta_tamano(n: int) -> str:
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}m"
    if n % 1000 == 0:
        return f"{n // 1000}k"
    return str(n)


def _contexto_ssl() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


_SSL_CONTEXT = _contexto_ssl()


def descargar_archivo(url: str, destino: Path, bloque: int = 1024 * 1024) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".part")

    if destino.exists() and destino.stat().st_size > 0:
        print(f"[amazon_img] Ya existe: {destino} ({destino.stat().st_size / (1024 * 1024):.1f} MB)")
        return destino

    descargado = parcial.stat().st_size if parcial.exists() else 0
    headers = {"User-Agent": "Mozilla/5.0 (Proyecto-BD2 Benchmark Downloader)"}
    if descargado > 0:
        headers["Range"] = f"bytes={descargado}-"

    req = urllib.request.Request(url, headers=headers)
    print(f"[amazon_img] Descargando {url} -> {destino} ...")
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CONTEXT) as resp:
        codigo = getattr(resp, "status", 200)
        modo = "ab" if (descargado > 0 and codigo == 206) else "wb"
        if modo == "wb":
            descargado = 0
        total_hdr = resp.headers.get("Content-Length")
        total = (descargado + int(total_hdr)) if total_hdr else None

        with open(parcial, modo) as f:
            while True:
                trozo = resp.read(bloque)
                if not trozo:
                    break
                f.write(trozo)
                descargado += len(trozo)
                if total:
                    pct = 100.0 * descargado / total
                    print(
                        f"\r  {descargado / (1024 * 1024):6.1f} / {total / (1024 * 1024):6.1f} MB ({pct:5.1f}%)",
                        end="",
                        flush=True,
                    )
                else:
                    print(f"\r  {descargado / (1024 * 1024):6.1f} MB descargados", end="", flush=True)
    print()
    parcial.replace(destino)
    return destino


def obtener_manifiesto(total_necesario: int, semilla: int, ruta_meta: Path) -> list[dict]:
    if MANIFIESTO_IDS.exists():
        with open(MANIFIESTO_IDS, "r", encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        if len(filas) >= total_necesario:
            print(f"[amazon_img] Manifiesto leído de {MANIFIESTO_IDS} ({len(filas):,} registros)")
            return filas[:total_necesario]

    dir_amazon = Path(preparar_amazon.DIR_SALIDA)
    prod_csv = dir_amazon / "productos.csv"
    img_csv = dir_amazon / "imagenes.csv"

    if not (prod_csv.exists() and img_csv.exists()):
        if not ruta_meta.exists():
            descargar_archivo(URL_META_ELECTRONICS, ruta_meta)
        print(f"[amazon_img] Extrayendo {total_necesario:,} productos desde {ruta_meta} ...")
        preparar_amazon.preparar(str(ruta_meta), None, str(dir_amazon), n=total_necesario, semilla=semilla)

    categorias = {}
    with open(prod_csv, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            categorias[row["id"]] = (
                row.get("subcategoria") or row.get("categoria") or "Electronics",
                row.get("nombre") or "",
            )

    manifiesto = []
    with open(img_csv, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pid = str(row["producto_id"])
            cat, nombre = categorias.get(pid, ("Electronics", ""))
            manifiesto.append({
                "id": pid,
                "asin": row["asin"],
                "categoria": cat,
                "titulo": nombre,
                "url": row["url"],
            })

    MANIFIESTO_IDS.parent.mkdir(parents=True, exist_ok=True)
    campos = ["id", "asin", "categoria", "titulo", "url"]
    with open(MANIFIESTO_IDS, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(manifiesto)
    print(f"[amazon_img] Manifiesto guardado en {MANIFIESTO_IDS} ({len(manifiesto):,} registros)")
    return manifiesto[:total_necesario]


def _descargar_una_imagen(item: dict, dir_imgs: Path, timeout: int = 20) -> tuple[str, Path | None, str | None]:
    pid = str(item["id"])
    url = item["url"]
    destino = dir_imgs / f"{pid}.jpg"
    if destino.exists() and destino.stat().st_size > 256:
        return pid, destino, None

    parcial = destino.with_suffix(".jpg.part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            datos = resp.read()
        if len(datos) <= 256:
            return pid, None, "archivo demasiado pequeno"
        with open(parcial, "wb") as f:
            f.write(datos)
        parcial.replace(destino)
        return pid, destino, None
    except Exception as exc:
        if parcial.exists():
            try:
                parcial.unlink()
            except OSError:
                pass
        return pid, None, f"{type(exc).__name__}: {exc}"


def descargar_imagenes(items: list[dict], dir_imgs: Path, workers: int = 16) -> tuple[list[dict], int]:
    dir_imgs.mkdir(parents=True, exist_ok=True)
    exitosos = {}
    errores = 0
    total = len(items)

    print(f"[amazon_img] Descargando {total:,} imágenes MAIN en {dir_imgs} ({workers} hilos)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_descargar_una_imagen, it, dir_imgs): it for it in items}
        for idx, fut in enumerate(concurrent.futures.as_completed(futuros), start=1):
            pid, ruta, err = fut.result()
            if ruta is not None:
                exitosos[pid] = ruta
            else:
                errores += 1
            if idx % 200 == 0 or idx == total:
                print(
                    f"\r  Progreso: {idx:,}/{total:,} ({len(exitosos):,} ok, {errores:,} fallos)",
                    end="",
                    flush=True,
                )
    print()

    ordenados = []
    for it in items:
        pid = str(it["id"])
        if pid in exitosos:
            copia = dict(it)
            copia["ruta"] = str(exitosos[pid].resolve())
            ordenados.append(copia)
    return ordenados, errores


def guardar_objetos_csv(ruta: Path, items: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["id", "ruta"])
        for it in items:
            escritor.writerow([it["id"], it["ruta"]])


def _ruta_relativa(ruta: str) -> str:
    try:
        return str(Path(ruta).resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(ruta).replace("\\", "/")


def ingestar_tablas_imagenes(items_base: list[dict], tamanos: list[int], data_dir: str,
                             metodo_indice: str = "HNSW", tabla_prefijo: str = "imagenes") -> None:
    from common.record import Record
    from engine.buffer_pool import BufferPool
    from engine.file_manager import FileManager
    from index.vector.registro import CONSTRUCTORES
    from multimedia import bovw
    from query import catalog_store
    from query.catalog import INDEX_VECTOR, Catalog
    from query.conexion import Conexion
    from text.ingesta import recortar_utf8
    from transaction.manager import TransactionManager

    os.makedirs(data_dir, exist_ok=True)
    pool = BufferPool(FileManager())
    catalog = Catalog()
    catalog_store.cargar(catalog, pool, data_dir)
    tmp_dir = os.path.join(data_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    conexion = Conexion(catalog, TransactionManager(pool=pool), tmp_dir=tmp_dir, pool=pool, data_dir=data_dir)

    por_id = {str(it["id"]): it for it in items_base}
    constructor = CONSTRUCTORES[metodo_indice]

    for n in tamanos:
        tabla = f"{tabla_prefijo}_{etiqueta_tamano(n)}"
        if catalog.existe_tabla(tabla):
            conexion.execute(f"DROP TABLE {tabla}")

        res_ct = conexion.execute(
            f"CREATE TABLE {tabla} ("
            "id INT PRIMARY KEY, asin VARCHAR(20), categoria VARCHAR(80), "
            "titulo VARCHAR(160), ruta VARCHAR(220))"
        )
        if not res_ct.ok:
            raise RuntimeError(f"Error creando {tabla}: {res_ct.error}")

        vectores, ids_col = bovw.cargar_coleccion("imagen", n)
        info = catalog.get_table(tabla)
        claves_pk = []
        rids = []
        rutas_rel = []

        for oid in ids_col:
            oid_str = str(oid)
            it = por_id[oid_str]
            id_num = int(it["id"])
            ruta_rel = recortar_utf8(_ruta_relativa(it["ruta"]), 220)
            registro = [
                id_num,
                recortar_utf8(str(it.get("asin", "")), 20),
                recortar_utf8(str(it.get("categoria", "")), 80),
                recortar_utf8(str(it.get("titulo", "")), 160),
                ruta_rel,
            ]
            rid = info.storage.insert(Record(registro), info.schema)
            claves_pk.append((id_num, rid))
            rids.append(rid)
            rutas_rel.append(ruta_rel)

        indice_pk, _ = catalog.get_indice(tabla, "id")
        claves_pk.sort(key=lambda p: (p[0], p[1].page_id, p[1].slot_id))
        indice_pk.bulk_load(claves_pk)

        indice_vec = constructor(rids, vectores, rutas=rutas_rel)
        ruta_npz = os.path.join(data_dir, f"{tabla}_ruta_{metodo_indice.lower()}_vector.npz")
        indice_vec.guardar(ruta_npz)
        catalog.register_index(tabla, "ruta", indice_vec, INDEX_VECTOR)
        catalog_store.guardar_tabla(data_dir, info)
        print(f"[amazon_img] Tabla '{tabla}' ingresada ({len(rids):,} filas, índice vectorial {metodo_indice})")

    pool.close_all()


def main(argv=None):
    cfg = cargar_config()
    n_consultas_cfg = cfg.get("vector", {}).get("consultas", 100)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--tamanos", nargs="+", default=cfg.get("tamanos", [1000, 10000, 100000]),
                        help="Tamaños de tablas a generar/ingestar (ej: 1k 10k 100k o 1000 10000 100000)")
    parser.add_argument("--consultas", type=int, default=n_consultas_cfg,
                        help="Cantidad de imágenes de consulta separadas de la base")
    parser.add_argument("--workers", type=int, default=16,
                        help="Hilos para descarga paralela de imágenes")
    parser.add_argument("--semilla", type=int, default=cfg.get("semilla", 42))
    parser.add_argument("--meta", default=preparar_amazon.META,
                        help="Ruta local a meta_Electronics.jsonl.gz")
    parser.add_argument("--salida", default=str(DIR_AMAZON_BENCH))
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "data"),
                        help="Directorio de datos del motor SQL donde se guardan las tablas (por defecto: data/)")
    parser.add_argument("--indice", default="HNSW", choices=("HNSW", "IVF", "EXACTO"),
                        help="Tipo de índice vectorial a registrar al usar --ingestar (por defecto: HNSW)")
    parser.add_argument("--solo-manifiesto", action="store_true",
                        help="Solo descarga/genera el manifiesto de URLs sin bajar los .jpg")
    parser.add_argument("--construir-bovw", action="store_true",
                        help="Ejecuta multimedia.construir al finalizar la descarga")
    parser.add_argument("--ingestar", action="store_true",
                        help="Construye BoVW y crea las tablas imagenes_1k/10k/100k en el motor para el frontend")
    args = parser.parse_args(argv)

    tamanos = parsear_tamanos(args.tamanos)
    max_base = max(tamanos)
    # Margen del 2% por si alguna URL vieja del CDN devuelve 404
    margen = max(50, int((max_base + args.consultas) * 0.02))
    total_objetivo = max_base + args.consultas + margen

    manifiesto = obtener_manifiesto(total_objetivo, args.semilla, Path(args.meta))
    if args.solo_manifiesto:
        return

    dir_salida = Path(args.salida)
    dir_imgs = dir_salida / "imgs"
    descargados, _errores = descargar_imagenes(manifiesto, dir_imgs, workers=args.workers)

    azar = random.Random(args.semilla)
    azar.shuffle(descargados)

    consultas = descargados[: args.consultas]
    base = descargados[args.consultas : args.consultas + max_base]

    guardar_objetos_csv(dir_salida / "objetos.csv", base)
    for t in tamanos:
        if t <= len(base):
            etiqueta = f"{t // 1000}k" if t % 1000 == 0 else str(t)
            guardar_objetos_csv(dir_salida / f"objetos_{etiqueta}.csv", base[:t])

    ruta_consultas = dir_salida / "consultas.csv"
    with open(ruta_consultas, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["id", "ruta", "categoria", "titulo"])
        for c in consultas:
            escritor.writerow([c["id"], c["ruta"], c["categoria"], c["titulo"]])

    etiquetas = {str(it["id"]): it["categoria"] for it in descargados}
    with open(dir_salida / "etiquetas.json", "w", encoding="utf-8") as f:
        json.dump(etiquetas, f, ensure_ascii=False, indent=2)

    print(
        f"[amazon_img] Listo: {len(base):,} imágenes base y {len(consultas):,} consultas en {dir_salida}"
    )

    if (args.construir_bovw or args.ingestar) and base:
        from multimedia import construir

        tamanos_validos = [t for t in tamanos if t <= len(base)]
        construir.main([
            "--tipo", "imagen",
            "--objetos", str(dir_salida / "objetos.csv"),
            "--n", ",".join(str(t) for t in tamanos_validos),
        ])
        if args.ingestar and tamanos_validos:
            ingestar_tablas_imagenes(base, tamanos_validos, args.data_dir, metodo_indice=args.indice)


if __name__ == "__main__":
    main()
