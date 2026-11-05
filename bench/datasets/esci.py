"""ESCI: descarga, subconjuntos 1k/10k/100k y consultas de 1, 3 y 5+ palabras."""
import argparse
import csv
import html
import json
import os
import random
import re
import ssl
import sys
import urllib.request
from pathlib import Path

import yaml

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = BENCH_DIR / "config.yaml"
DIR_ESCI = BENCH_DIR / "data" / "esci"
DIR_IDS = BENCH_DIR / "datasets" / "ids"

URL_PRODUCTOS = (
    "https://github.com/amazon-science/esci-data/raw/main/"
    "shopping_queries_dataset/shopping_queries_dataset_products.parquet"
)
URL_EJEMPLOS = (
    "https://github.com/amazon-science/esci-data/raw/main/"
    "shopping_queries_dataset/shopping_queries_dataset_examples.parquet"
)

ETIQUETAS_RELEVANTES = {"E", "S", "Exact", "Substitute"}
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def cargar_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"semilla": 42, "tamanos": [1000, 10000, 100000], "k": 10}


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


def limpiar_texto(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor)
    if texto.lower() in ("nan", "none", "<na>"):
        return ""
    texto = html.unescape(_HTML_RE.sub(" ", texto))
    return _WS_RE.sub(" ", texto).strip()


def _contexto_ssl() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


def descargar_archivo(url: str, destino: Path, bloque: int = 1024 * 1024) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".part")

    if destino.exists() and destino.stat().st_size > 0:
        print(f"[esci] Ya existe: {destino} ({destino.stat().st_size / (1024 * 1024):.1f} MB)")
        return destino

    descargado = parcial.stat().st_size if parcial.exists() else 0
    headers = {"User-Agent": "Mozilla/5.0 (Proyecto-BD2 Benchmark Downloader)"}
    if descargado > 0:
        headers["Range"] = f"bytes={descargado}-"

    req = urllib.request.Request(url, headers=headers)
    print(f"[esci] Descargando {url} -> {destino} ...")
    with urllib.request.urlopen(req, timeout=60, context=_contexto_ssl()) as resp:
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


def _leer_parquet(ruta: Path, columnas=None, locale=None):
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        # el parquet de productos es un solo row group de ~2 GB: por lotes para no cargarlo entero
        archivo = pq.ParquetFile(ruta)
        lotes = []
        for lote in archivo.iter_batches(batch_size=50_000, columns=columnas):
            if locale and locale != "all":
                lote = lote.filter(pc.equal(lote.column("product_locale"), locale))
            lotes.append(lote)
        return pa.Table.from_batches(lotes).to_pandas()
    except ImportError as exc:
        raise SystemExit(
            f"Error al leer '{ruta.name}': se necesita 'pyarrow' o 'fastparquet' para abrir archivos Parquet.\n"
            f"Instálalo ejecutando: pip install pyarrow\nDetalle: {exc}"
        ) from exc


def seleccionar_productos(ruta_productos: Path, max_n: int, locale: str, semilla: int) -> list[dict]:
    cols = [
        "product_id",
        "product_title",
        "product_description",
        "product_bullet_point",
        "product_brand",
        "product_locale",
    ]
    df = _leer_parquet(ruta_productos, columnas=cols, locale=locale)
    if locale != "all" and len(df) < max_n:
        print(
            f"[esci] Aviso: locale='{locale}' tiene {len(df)} filas (< {max_n}); "
            "completando con el resto de locales."
        )
        df = _leer_parquet(ruta_productos, columnas=cols)

    productos = []
    vistos = set()
    for pid_raw, tit_raw, desc_raw, bul_raw, mar_raw, loc_raw in zip(
        df["product_id"],
        df["product_title"],
        df["product_description"],
        df["product_bullet_point"],
        df["product_brand"],
        df["product_locale"],
    ):
        pid = limpiar_texto(pid_raw)
        if not pid or pid in vistos:
            continue
        titulo = limpiar_texto(tit_raw)
        if not titulo:
            continue
        desc = limpiar_texto(desc_raw)
        bullets = limpiar_texto(bul_raw)
        cuerpo = " ".join(p for p in (desc, bullets) if p)
        if not cuerpo:
            continue
        marca = limpiar_texto(mar_raw)
        loc = limpiar_texto(loc_raw)
        vistos.add(pid)
        productos.append({
            "product_id": pid,
            "titulo": titulo,
            "descripcion": cuerpo,
            "marca": marca,
            "idioma": loc,
        })

    azar = random.Random(semilla)
    azar.shuffle(productos)
    elegidos = productos[:max_n]
    for idx, prod in enumerate(elegidos, start=1):
        prod["id"] = idx
    return elegidos


def extraer_consultas(ruta_ejemplos: Path, id_por_pid: dict[str, int], tamanos: list[int],
                      locale: str, max_por_grupo: int, semilla: int) -> dict:
    cols = ["query", "product_id", "product_locale", "esci_label"]
    df = _leer_parquet(ruta_ejemplos, columnas=cols, locale=locale)
    if locale != "all":
        df = df[df["product_locale"] == locale]
    df = df[df["esci_label"].isin(ETIQUETAS_RELEVANTES)]
    df = df[df["product_id"].isin(id_por_pid)]

    relevantes_por_query: dict[str, set[int]] = {}
    for q_raw, pid_raw in zip(df["query"], df["product_id"]):
        doc_id = id_por_pid.get(str(pid_raw))
        if doc_id is None:
            continue
        q = limpiar_texto(q_raw)
        if not q:
            continue
        relevantes_por_query.setdefault(q, set()).add(doc_id)

    grupos = {"1_palabra": [], "3_palabras": [], "5_mas_palabras": []}
    for q, doc_ids in relevantes_por_query.items():
        palabras = q.split()
        n_pal = len(palabras)
        if n_pal == 1:
            clave = "1_palabra"
        elif n_pal == 3:
            clave = "3_palabras"
        elif n_pal >= 5:
            clave = "5_mas_palabras"
        else:
            continue

        por_tamano = {}
        for t in tamanos:
            rels_t = sorted(d for d in doc_ids if d <= t)
            if rels_t:
                por_tamano[str(t)] = rels_t
        if str(max(tamanos)) in por_tamano:
            grupos[clave].append({
                "query": q,
                "num_palabras": n_pal,
                "relevantes_por_tamano": por_tamano,
            })

    azar = random.Random(semilla)
    salida = {}
    for clave, lista in grupos.items():
        # Prioriza consultas con relevantes ya desde el subconjunto mas pequeno
        lista.sort(key=lambda item: (-len(item["relevantes_por_tamano"]), -len(
            item["relevantes_por_tamano"].get(str(min(tamanos)), [])
        ), item["query"]))
        candidatos = lista[: max_por_grupo * 3]
        azar.shuffle(candidatos)
        salida[clave] = candidatos[:max_por_grupo]
    return salida


def guardar_csv_productos(ruta: Path, productos: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = ["id", "product_id", "titulo", "descripcion", "marca", "idioma"]
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        for p in productos:
            escritor.writerow({c: p[c] for c in campos})


def main(argv=None):
    cfg = cargar_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--tamanos", nargs="+", default=cfg.get("tamanos", [1000, 10000, 100000]),
                        help="Tamaños de tablas a generar/ingestar (ej: 1k 10k 100k o 1000 10000 100000)")
    parser.add_argument("--locale", default="es", choices=("es", "us", "all"),
                        help="Idioma del dataset ESCI (por defecto: es)")
    parser.add_argument("--consultas-por-grupo", type=int, default=30,
                        help="Cantidad de consultas para cada longitud (1, 3 y 5+ palabras)")
    parser.add_argument("--semilla", type=int, default=cfg.get("semilla", 42))
    parser.add_argument("--salida", default=str(DIR_ESCI))
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "data"),
                        help="Directorio de datos del motor SQL donde se guardan las tablas (por defecto: data/)")
    parser.add_argument("--solo-descargar", action="store_true",
                        help="Solo descarga los archivos Parquet sin procesarlos")
    parser.add_argument("--ingestar", action="store_true",
                        help="Carga las tablas documentos_1k/10k/100k en el motor con SPIMI")
    args = parser.parse_args(argv)

    dir_salida = Path(args.salida)
    dir_salida.mkdir(parents=True, exist_ok=True)
    DIR_IDS.mkdir(parents=True, exist_ok=True)

    ruta_prod = descargar_archivo(URL_PRODUCTOS, dir_salida / "shopping_queries_dataset_products.parquet")
    ruta_ejem = descargar_archivo(URL_EJEMPLOS, dir_salida / "shopping_queries_dataset_examples.parquet")

    if args.solo_descargar:
        print("[esci] Descarga completada.")
        return

    tamanos = parsear_tamanos(args.tamanos)
    max_n = max(tamanos)
    print(f"[esci] Seleccionando {max_n:,} productos (locale={args.locale}, semilla={args.semilla})...")
    productos = seleccionar_productos(ruta_prod, max_n, args.locale, args.semilla)
    print(f"[esci] {len(productos):,} productos seleccionados.")

    csv_principal = dir_salida / "productos.csv"
    guardar_csv_productos(csv_principal, productos)
    print(f"[esci] CSV guardado en {csv_principal}")

    for t in tamanos:
        if t <= len(productos):
            etiqueta = f"{t // 1000}k" if t % 1000 == 0 else str(t)
            guardar_csv_productos(dir_salida / f"productos_{etiqueta}.csv", productos[:t])

    ruta_ids = DIR_IDS / "esci_product_ids.txt"
    with open(ruta_ids, "w", encoding="utf-8") as f:
        for p in productos:
            f.write(f"{p['id']}\t{p['product_id']}\n")

    id_por_pid = {p["product_id"]: p["id"] for p in productos}
    consultas = extraer_consultas(
        ruta_ejem, id_por_pid, tamanos, args.locale, args.consultas_por_grupo, args.semilla
    )

    for destino_q in (dir_salida / "consultas.json", DIR_IDS / "esci_consultas.json"):
        with open(destino_q, "w", encoding="utf-8") as f:
            json.dump(consultas, f, ensure_ascii=False, indent=2)

    resumen_q = {k: len(v) for k, v in consultas.items()}
    print(f"[esci] Consultas extraídas por longitud: {resumen_q}")

    if args.ingestar:
        from text import ingesta

        idioma_motor = "spanish" if args.locale == "es" else "english"
        ingesta.main([
            str(csv_principal),
            "--texto", "titulo", "descripcion",
            "--id", "id",
            "--metadata", "marca",
            "--tabla", "documentos",
            "--tamanos", *[str(t) for t in tamanos],
            "--idioma", idioma_motor,
            "--data-dir", str(args.data_dir),
            "--reemplazar",
        ])


if __name__ == "__main__":
    main()
