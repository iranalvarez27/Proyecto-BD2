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
ETIQUETAS_NO_RELEVANTES = {"C", "I", "Complement", "Irrelevant"}
GRUPOS = ("1_palabra", "3_palabras", "5_mas_palabras")
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


def leer_productos(ruta_productos: Path, locale: str, minimo: int) -> dict[str, dict]:
    cols = [
        "product_id",
        "product_title",
        "product_description",
        "product_bullet_point",
        "product_brand",
        "product_locale",
    ]
    df = _leer_parquet(ruta_productos, columnas=cols, locale=locale)
    if locale != "all" and len(df) < minimo:
        print(
            f"[esci] Aviso: locale='{locale}' tiene {len(df)} filas (< {minimo}); "
            "completando con el resto de locales."
        )
        df = _leer_parquet(ruta_productos, columnas=cols)

    productos = {}
    for pid_raw, tit_raw, desc_raw, bul_raw, mar_raw, loc_raw in zip(
        df["product_id"],
        df["product_title"],
        df["product_description"],
        df["product_bullet_point"],
        df["product_brand"],
        df["product_locale"],
    ):
        pid = limpiar_texto(pid_raw)
        if not pid or pid in productos:
            continue
        titulo = limpiar_texto(tit_raw)
        if not titulo:
            continue
        desc = limpiar_texto(desc_raw)
        bullets = limpiar_texto(bul_raw)
        cuerpo = " ".join(p for p in (desc, bullets) if p)
        if not cuerpo:
            continue
        productos[pid] = {
            "product_id": pid,
            "titulo": titulo,
            "descripcion": cuerpo,
            "marca": limpiar_texto(mar_raw),
            "idioma": limpiar_texto(loc_raw),
        }
    return productos


def leer_juicios(ruta_ejemplos: Path, locale: str, productos: dict) -> dict[int, dict]:
    cols = ["query_id", "query", "product_id", "product_locale", "esci_label"]
    df = _leer_parquet(ruta_ejemplos, columnas=cols, locale=locale)
    juicios = {}
    for qid, q_raw, pid_raw, etiqueta in zip(df["query_id"], df["query"], df["product_id"], df["esci_label"]):
        pid = limpiar_texto(pid_raw)
        q = limpiar_texto(q_raw)
        if pid not in productos or not q:
            continue
        j = juicios.setdefault(int(qid), {"query": q, "relevantes": set(), "no_relevantes": set()})
        if etiqueta in ETIQUETAS_RELEVANTES:
            j["relevantes"].add(pid)
        elif etiqueta in ETIQUETAS_NO_RELEVANTES:
            j["no_relevantes"].add(pid)
    return juicios


def _grupo(consulta: str):
    n = len(consulta.split())
    if n >= 5:
        return "5_mas_palabras"
    return {1: "1_palabra", 3: "3_palabras"}.get(n)


def seleccionar(ruta_productos: Path, ruta_ejemplos: Path, tamanos: list[int], locale: str,
                por_grupo: int, n_rel: int, n_no_rel: int, semilla: int) -> tuple[list[dict], dict]:
    productos = leer_productos(ruta_productos, locale, max(tamanos))
    juicios = leer_juicios(ruta_ejemplos, locale, productos)
    azar = random.Random(semilla)

    candidatas = {g: [] for g in GRUPOS}
    for qid in sorted(juicios):
        g = _grupo(juicios[qid]["query"])
        if g and len(juicios[qid]["relevantes"]) >= n_rel:
            candidatas[g].append(qid)

    elegidas = []
    for g in GRUPOS:
        if len(candidatas[g]) < por_grupo:
            raise SystemExit(f"[esci] Solo hay {len(candidatas[g])} consultas de '{g}' con {n_rel}+ relevantes")
        azar.shuffle(candidatas[g])
        elegidas += [(g, qid) for qid in candidatas[g][:por_grupo]]

    nucleo = {}
    juzgados = set()
    for _, qid in elegidas:
        j = juicios[qid]
        no_rel = sorted(j["no_relevantes"] - j["relevantes"])
        for pid in azar.sample(sorted(j["relevantes"]), n_rel) + azar.sample(no_rel, min(n_no_rel, len(no_rel))):
            nucleo[pid] = None
        juzgados |= j["relevantes"] | j["no_relevantes"]
    if len(nucleo) > min(tamanos):
        raise SystemExit(
            f"[esci] Los {len(nucleo)} productos juzgados no entran en {min(tamanos)}; "
            "bajar --consultas-por-grupo o --relevantes-por-consulta"
        )

    # los juzgados que no entraron al nucleo quedan fuera: serian relevantes sin marcar
    relleno = [pid for pid in productos if pid not in juzgados]
    azar.shuffle(relleno)
    faltan = max(tamanos) - len(nucleo)
    if len(relleno) < faltan:
        raise SystemExit(f"[esci] Solo hay {len(relleno):,} productos de relleno y faltan {faltan:,}")
    # el nucleo va dentro del tamano menor, y por ser prefijos queda en los tres
    en_menor = min(tamanos) - len(nucleo)
    primeros = list(nucleo) + relleno[:en_menor]
    azar.shuffle(primeros)
    orden = primeros + relleno[en_menor:faltan]
    print(f"[esci] {len(nucleo)} productos juzgados en todos los tamanos y {faltan:,} de relleno")

    elegidos = [{**productos[pid], "id": idx} for idx, pid in enumerate(orden, start=1)]
    id_por_pid = {p["product_id"]: p["id"] for p in elegidos}

    consultas = {g: [] for g in GRUPOS}
    for g, qid in elegidas:
        j = juicios[qid]
        rel = sorted(id_por_pid[p] for p in j["relevantes"] if p in nucleo)
        no_rel = sorted(id_por_pid[p] for p in j["no_relevantes"] - j["relevantes"] if p in nucleo)
        consultas[g].append({
            "query_id": qid,
            "query": j["query"],
            "num_palabras": len(j["query"].split()),
            "relevantes_por_tamano": {str(t): rel for t in tamanos},
            "no_relevantes": no_rel,
        })
    return elegidos, consultas


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
    parser.add_argument("--relevantes-por-consulta", type=int, default=6,
                        help="Relevantes (E o S) de cada consulta que entran en todos los tamanos")
    parser.add_argument("--no-relevantes-por-consulta", type=int, default=2,
                        help="Juzgados no relevantes (C o I) de cada consulta que entran en todos los tamanos")
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
    print(f"[esci] Seleccionando {max(tamanos):,} productos (locale={args.locale}, semilla={args.semilla})...")
    productos, consultas = seleccionar(
        ruta_prod, ruta_ejem, tamanos, args.locale, args.consultas_por_grupo,
        args.relevantes_por_consulta, args.no_relevantes_por_consulta, args.semilla,
    )
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
