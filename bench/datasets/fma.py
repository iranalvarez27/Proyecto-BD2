import argparse
import csv
import json
import math
import os
import random
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

import yaml

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = BENCH_DIR / "config.yaml"
DIR_FMA = BENCH_DIR / "data" / "fma"
DIR_IDS = BENCH_DIR / "datasets" / "ids"

URL_METADATA = "https://os.unil.cloud.switch.ch/fma/fma_metadata.zip"
URLS_AUDIO = {
    "medium": "https://os.unil.cloud.switch.ch/fma/fma_medium.zip",
    "small": "https://os.unil.cloud.switch.ch/fma/fma_small.zip",
}

# El largo del segmento sale de multimedia/config.py: una sola fuente de verdad para la
# extraccion (cache, ExtractFeatures) y para estas tablas.
from multimedia.config import SEG_S  # noqa: E402

DURACION_PISTA_S = 30.0
# Muchas pistas de FMA duran ~29.97 s y el ultimo trozo incompleto se descarta: se cuentan
# solo los segmentos completos con la duracion util
DURACION_UTIL_S = 29.9
SEGMENTOS_POR_PISTA = int(DURACION_UTIL_S // SEG_S)


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


def descargar_archivo(url: str, destino: Path, bloque: int = 1024 * 1024) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".part")

    if destino.exists() and destino.stat().st_size > 0:
        print(f"[fma] Ya existe: {destino} ({destino.stat().st_size / (1024 * 1024):.1f} MB)")
        return destino

    descargado = parcial.stat().st_size if parcial.exists() else 0
    headers = {"User-Agent": "Mozilla/5.0 (Proyecto-BD2 Benchmark Downloader)"}
    if descargado > 0:
        headers["Range"] = f"bytes={descargado}-"

    req = urllib.request.Request(url, headers=headers)
    print(f"[fma] Descargando {url} -> {destino} ...")
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
                        f"\r  {descargado / (1024 * 1024):7.1f} / {total / (1024 * 1024):7.1f} MB ({pct:5.1f}%)",
                        end="",
                        flush=True,
                    )
                else:
                    print(f"\r  {descargado / (1024 * 1024):7.1f} MB descargados", end="", flush=True)
    print()
    parcial.replace(destino)
    return destino


def extraer_tracks_csv(zip_meta: Path, dir_destino: Path) -> Path:
    ruta_tracks = dir_destino / "fma_metadata" / "tracks.csv"
    if ruta_tracks.exists() and ruta_tracks.stat().st_size > 0:
        return ruta_tracks

    print(f"[fma] Extrayendo tracks.csv desde {zip_meta} ...")
    with zipfile.ZipFile(zip_meta, "r") as zf:
        miembro = next((m for m in zf.namelist() if m.endswith("tracks.csv")), None)
        if miembro is None:
            raise RuntimeError(f"No se encontró tracks.csv dentro de {zip_meta}")
        zf.extract(miembro, path=dir_destino)
    extracted = dir_destino / miembro
    return extracted


def extraer_audios_zip(zip_audio: Path, dir_destino: Path) -> Path:
    print(f"[fma] Verificando/extrayendo audios desde {zip_audio} en {dir_destino} ...")
    with zipfile.ZipFile(zip_audio, "r") as zf:
        mp3s = [m for m in zf.namelist() if m.lower().endswith(".mp3")]
        total = len(mp3s)
        nuevos = 0
        for idx, miembro in enumerate(mp3s, start=1):
            ruta_out = dir_destino / miembro
            if not (ruta_out.exists() and ruta_out.stat().st_size > 1024):
                zf.extract(miembro, path=dir_destino)
                nuevos += 1
            if idx % 500 == 0 or idx == total:
                print(
                    f"\r  Audios revisados: {idx:,}/{total:,} ({nuevos:,} extraídos nuevos)",
                    end="",
                    flush=True,
                )
    print()
    return dir_destino


def leer_metadatos_tracks(ruta_tracks_csv: Path) -> dict[int, dict]:
    metadatos = {}
    with open(ruta_tracks_csv, "r", encoding="utf-8", errors="replace", newline="") as f:
        lector = csv.reader(f)
        secciones = next(lector)
        campos = next(lector)
        _fila_id = next(lector)

        indices = {(s.strip(), c.strip()): i for i, (s, c) in enumerate(zip(secciones, campos))}
        idx_subset = indices.get(("set", "subset"))
        idx_genre = indices.get(("track", "genre_top"))
        idx_title = indices.get(("track", "title"))
        idx_artist = indices.get(("artist", "name"))

        for fila in lector:
            if not fila or not fila[0].strip().isdigit():
                continue
            tid = int(fila[0].strip())
            metadatos[tid] = {
                "track_id": tid,
                "subset": fila[idx_subset].strip() if idx_subset is not None and idx_subset < len(fila) else "",
                "genero": (
                    fila[idx_genre].strip()
                    if idx_genre is not None and idx_genre < len(fila) and fila[idx_genre].strip()
                    else "Unknown"
                ),
                "titulo": fila[idx_title].strip() if idx_title is not None and idx_title < len(fila) else "",
                "artista": fila[idx_artist].strip() if idx_artist is not None and idx_artist < len(fila) else "",
            }
    return metadatos


def descubrir_pistas_locales(dir_fma: Path, variante: str, metadatos: dict[int, dict]) -> list[dict]:
    carpeta_audio = dir_fma / f"fma_{variante}"
    if not carpeta_audio.exists():
        return []

    pistas = []
    for ruta_mp3 in sorted(carpeta_audio.rglob("*.mp3")):
        if ruta_mp3.stat().st_size <= 4096:
            continue
        nombre = ruta_mp3.stem
        if not nombre.isdigit():
            continue
        tid = int(nombre)
        meta = metadatos.get(tid, {
            "track_id": tid,
            "subset": variante,
            "genero": "Unknown",
            "titulo": f"Track {tid}",
            "artista": "",
        })
        pistas.append({
            **meta,
            "ruta": str(ruta_mp3.resolve()),
        })
    return pistas


def expandir_segmentos(pistas: list[dict], seg_s: float = SEG_S,
                       n_seg: int = SEGMENTOS_POR_PISTA) -> list[dict]:
    segmentos = []
    for p in pistas:
        tid = p["track_id"]
        for s in range(n_seg):
            inicio = round(s * seg_s, 2)
            fin = round((s + 1) * seg_s, 2)
            segmentos.append({
                "id_segmento": json.dumps([str(tid), s]),
                "track_id": tid,
                "segmento": s,
                "seg_inicio": inicio,
                "seg_fin": fin,
                "ruta": p["ruta"],
                "genero": p["genero"],
                "titulo": p["titulo"],
                "artista": p["artista"],
            })
    return segmentos


def guardar_segmentos_csv(ruta: Path, segmentos: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = ["id_segmento", "track_id", "segmento", "seg_inicio", "seg_fin", "ruta", "genero", "titulo", "artista"]
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(segmentos)


def guardar_pistas_csv(ruta: Path, pistas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["id", "ruta"])
        for p in pistas:
            escritor.writerow([p["track_id"], p["ruta"]])


def _ruta_relativa(ruta: str) -> str:
    try:
        return str(Path(ruta).resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(ruta).replace("\\", "/")


def ingestar_tablas_audio(pistas_base: list[dict], tamanos: list[int], data_dir: str,
                          metodo_indice: str = "HNSW", tabla_prefijo: str = "audios") -> None:
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

    por_track = {str(p["track_id"]): p for p in pistas_base}
    constructor = CONSTRUCTORES[metodo_indice]

    for n in tamanos:
        tabla = f"{tabla_prefijo}_{etiqueta_tamano(n)}"
        if catalog.existe_tabla(tabla):
            conexion.execute(f"DROP TABLE {tabla}")

        res_ct = conexion.execute(
            f"CREATE TABLE {tabla} ("
            "id INT PRIMARY KEY, track_id INT, segmento INT, "
            "seg_inicio DOUBLE, seg_fin DOUBLE, genero VARCHAR(60), "
            "titulo VARCHAR(120), artista VARCHAR(100), ruta VARCHAR(220))"
        )
        if not res_ct.ok:
            raise RuntimeError(f"Error creando {tabla}: {res_ct.error}")

        vectores, ids_col = bovw.cargar_coleccion("audio", n)
        info = catalog.get_table(tabla)
        claves_pk = []
        rids = []
        rutas_rel = []

        for fila_idx, oid in enumerate(ids_col, start=1):
            if isinstance(oid, (tuple, list)) and len(oid) >= 2:
                tid_str, seg_idx = str(oid[0]), int(oid[1])
            else:
                tid_str, seg_idx = str(oid), 0
            p = por_track.get(tid_str, {
                "track_id": int(tid_str) if tid_str.isdigit() else fila_idx,
                "genero": "Unknown",
                "titulo": f"Track {tid_str}",
                "artista": "",
                "ruta": "",
            })
            inicio = round(seg_idx * SEG_S, 2)
            fin = round((seg_idx + 1) * SEG_S, 2)
            ruta_rel = recortar_utf8(_ruta_relativa(p["ruta"]), 220)
            registro = [
                fila_idx,
                int(p["track_id"]),
                seg_idx,
                float(inicio),
                float(fin),
                recortar_utf8(str(p.get("genero", "Unknown")), 60),
                recortar_utf8(str(p.get("titulo", "")), 120),
                recortar_utf8(str(p.get("artista", "")), 100),
                ruta_rel,
            ]
            rid = info.storage.insert(Record(registro), info.schema)
            claves_pk.append((fila_idx, rid))
            rids.append(rid)
            rutas_rel.append((ruta_rel, seg_idx))   # clave (ruta, segmento) del indice vectorial

        indice_pk, _ = catalog.get_indice(tabla, "id")
        claves_pk.sort(key=lambda p: (p[0], p[1].page_id, p[1].slot_id))
        indice_pk.bulk_load(claves_pk)

        indice_vec = constructor(rids, vectores, rutas=rutas_rel, n_coleccion=n)   # IDF de la coleccion de n
        ruta_npz = os.path.join(data_dir, f"{tabla}_ruta_{metodo_indice.lower()}_vector.npz")
        indice_vec.guardar(ruta_npz)
        catalog.register_index(tabla, "ruta", indice_vec, INDEX_VECTOR)
        catalog_store.guardar_tabla(data_dir, info)
        print(f"[fma] Tabla '{tabla}' ingresada ({len(rids):,} segmentos de {SEG_S:g}s, índice vectorial {metodo_indice})")

    pool.close_all()


def main(argv=None):
    cfg = cargar_config()
    n_consultas_cfg = cfg.get("vector", {}).get("consultas", 100)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variante", default="medium", choices=("small", "medium"),
                        help=f"Variante de FMA a descargar: medium (25k pistas, ~22 GB, ~{25_000 * SEGMENTOS_POR_PISTA:,} segmentos de {SEG_S:g} s; "
                             f"necesaria para la tabla de 100k) o small (8k pistas, ~7.2 GB, ~{8_000 * SEGMENTOS_POR_PISTA:,} segmentos)")
    parser.add_argument("-n", "--tamanos", nargs="+", default=cfg.get("tamanos", [1000, 10000, 100000]),
                        help=f"Tamaños de tablas en segmentos de {SEG_S:g} s (ej: 1k 10k 100k o 1000 10000 100000)")
    parser.add_argument("--consultas", type=int, default=n_consultas_cfg,
                        help=f"Cantidad de segmentos de {SEG_S:g} s separados como consultas")
    parser.add_argument("--semilla", type=int, default=cfg.get("semilla", 42))
    parser.add_argument("--procesos", type=int, default=min(8, os.cpu_count() or 1),
                        help="Procesos para extraer descriptores en multimedia.construir (por defecto: min(8, nucleos)). En Windows, sin esto la extraccion corre en un solo proceso")
    parser.add_argument("--salida", default=str(DIR_FMA))
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "data"),
                        help="Directorio de datos del motor SQL donde se guardan las tablas (por defecto: data/)")
    parser.add_argument("--indice", default="HNSW", choices=("HNSW", "IVF", "EXACTO"),
                        help="Tipo de índice vectorial a registrar al usar --ingestar (por defecto: HNSW)")
    parser.add_argument("--solo-descargar", action="store_true",
                        help="Solo descarga los archivos .zip sin descomprimir ni procesar")
    parser.add_argument("--construir-bovw", action="store_true",
                        help="Ejecuta multimedia.construir --tipo audio al terminar")
    parser.add_argument("--ingestar", action="store_true",
                        help="Construye BoAW y crea las tablas audios_1k/10k/100k en el motor para el frontend")
    args = parser.parse_args(argv)

    dir_salida = Path(args.salida)
    dir_salida.mkdir(parents=True, exist_ok=True)
    DIR_IDS.mkdir(parents=True, exist_ok=True)

    ruta_tracks_csv = dir_salida / "fma_metadata" / "tracks.csv"
    carpeta_audio = dir_salida / f"fma_{args.variante}"

    if ruta_tracks_csv.exists() and ruta_tracks_csv.stat().st_size > 0:
        print(f"[fma] Ya existe metadatos locales: {ruta_tracks_csv}")
    else:
        zip_meta = descargar_archivo(URL_METADATA, dir_salida / "fma_metadata.zip")
        ruta_tracks_csv = extraer_tracks_csv(zip_meta, dir_salida)

    tiene_audios_locales = carpeta_audio.exists() and any(carpeta_audio.glob("**/*.mp3"))
    if tiene_audios_locales:
        print(f"[fma] Ya existen audios locales en: {carpeta_audio}")
    else:
        url_audio = URLS_AUDIO[args.variante]
        zip_audio = descargar_archivo(url_audio, dir_salida / f"fma_{args.variante}.zip")
        if args.solo_descargar:
            print("[fma] Descarga de archivos .zip completada.")
            return
        extraer_audios_zip(zip_audio, dir_salida)

    if args.solo_descargar:
        print("[fma] Descarga completada.")
        return

    metadatos = leer_metadatos_tracks(ruta_tracks_csv)
    pistas = descubrir_pistas_locales(dir_salida, args.variante, metadatos)
    if not pistas:
        raise SystemExit(f"No se encontraron archivos .mp3 en {dir_salida / ('fma_' + args.variante)}")

    azar = random.Random(args.semilla)
    azar.shuffle(pistas)

    tamanos = parsear_tamanos(args.tamanos)
    max_segmentos = max(tamanos)
    # SEGMENTOS_POR_PISTA ya cuenta solo segmentos completos; el margen del 12% (minimo 15
    # pistas) cubre MP3 danados y pistas mas cortas.
    pistas_teoricas = math.ceil(max_segmentos / SEGMENTOS_POR_PISTA)
    margen_pistas = max(15, math.ceil(pistas_teoricas * 0.12))
    pistas_para_base = min(len(pistas) - 1, pistas_teoricas + margen_pistas)
    pistas_para_consultas = min(args.consultas, max(1, len(pistas) - pistas_para_base))

    pistas_consulta = pistas[:pistas_para_consultas]
    pistas_base = pistas[pistas_para_consultas : pistas_para_consultas + pistas_para_base]

    # 1 segmento aleatorio de SEG_S segundos por cada pista de consulta (para no repetir la misma cancion)
    consultas = []
    for p in pistas_consulta[: args.consultas]:
        seg_idx = azar.randrange(SEGMENTOS_POR_PISTA)
        inicio = round(seg_idx * SEG_S, 2)
        fin = round((seg_idx + 1) * SEG_S, 2)
        consultas.append({
            "id_segmento": json.dumps([str(p["track_id"]), seg_idx]),
            "track_id": p["track_id"],
            "segmento": seg_idx,
            "seg_inicio": inicio,
            "seg_fin": fin,
            "ruta": p["ruta"],
            "genero": p["genero"],
            "titulo": p["titulo"],
            "artista": p["artista"],
        })

    segmentos_base = expandir_segmentos(pistas_base)
    guardar_pistas_csv(dir_salida / "objetos.csv", pistas_base)
    guardar_segmentos_csv(dir_salida / "segmentos.csv", segmentos_base[:max_segmentos])
    guardar_segmentos_csv(dir_salida / "consultas.csv", consultas)

    for t in tamanos:
        if t > len(segmentos_base):
            print(f"[fma] AVISO: la tabla de {t:,} segmentos no se puede armar: la variante "
                  f"'{args.variante}' solo da {len(segmentos_base):,} segmentos de {SEG_S:g} s. "
                  f"Use --variante medium para llegar a 100k.")
        if t <= len(segmentos_base):
            etiqueta = f"{t // 1000}k" if t % 1000 == 0 else str(t)
            guardar_segmentos_csv(dir_salida / f"segmentos_{etiqueta}.csv", segmentos_base[:t])
            base_t = math.ceil(t / SEGMENTOS_POR_PISTA)
            n_pistas_t = min(len(pistas_base), base_t + max(15, math.ceil(base_t * 0.12)))
            guardar_pistas_csv(dir_salida / f"objetos_{etiqueta}.csv", pistas_base[:n_pistas_t])

    etiquetas = {str(p["track_id"]): p["genero"] for p in pistas}
    with open(dir_salida / "etiquetas.json", "w", encoding="utf-8") as f:
        json.dump(etiquetas, f, ensure_ascii=False, indent=2)

    ruta_ids = DIR_IDS / f"fma_{args.variante}_tracks.csv"
    with open(ruta_ids, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["track_id", "genero", "titulo", "artista", "rol"])
        for p in pistas_consulta:
            escritor.writerow([p["track_id"], p["genero"], p["titulo"], p["artista"], "consulta"])
        for p in pistas_base:
            escritor.writerow([p["track_id"], p["genero"], p["titulo"], p["artista"], "base"])

    print(
        f"[fma] Listo: {len(pistas_base):,} pistas base -> {len(segmentos_base[:max_segmentos]):,} "
        f"segmentos de {SEG_S}s y {len(consultas):,} consultas en {dir_salida}"
    )

    if (args.construir_bovw or args.ingestar) and pistas_base:
        from multimedia import construir

        tamanos_validos = [t for t in tamanos if t <= len(segmentos_base)]
        if not tamanos_validos:
            raise SystemExit(f"[fma] Ningun tamano pedido ({tamanos}) cabe en los {len(segmentos_base):,} "
                             f"segmentos de {SEG_S:g} s disponibles en la variante '{args.variante}'")
        construir.main([
            "--tipo", "audio",
            "--objetos", str(dir_salida / "objetos.csv"),
            "--n", ",".join(str(t) for t in tamanos_validos),
            "--workers", str(max(1, args.procesos)),
        ])
        if args.ingestar and tamanos_validos:
            ingestar_tablas_audio(pistas_base, tamanos_validos, args.data_dir, metodo_indice=args.indice)


if __name__ == "__main__":
    main()
