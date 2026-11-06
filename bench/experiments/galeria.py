import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl_cache"))
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bench.datasets.amazon_img import DIR_AMAZON_BENCH, parsear_tamanos
from bench.datasets.fma import DIR_FMA
from index.vector.exacto import knn_exacto_lote
from multimedia import bovw, config as mm_config

DIR_RESULTS = BENCH_DIR / "results"
JSON_GALERIA = DIR_RESULTS / "galeria.json"
PNG_GALERIA_IMG = DIR_RESULTS / "galeria_imagenes.png"
MD_GALERIA_AUDIO = DIR_RESULTS / "galeria_audio.md"

METRICAS = ("euclidean", "cosine")


def _resolver_n_disponible(tipo: str, n_pedido: int) -> int:
    dir_cols = mm_config.directorio_colecciones(tipo)
    disponibles = []
    if dir_cols.exists():
        for p in dir_cols.iterdir():
            if p.is_dir() and p.name.isdigit() and (p / "vectores.npy").exists():
                disponibles.append(int(p.name))
    if not disponibles:
        raise FileNotFoundError(
            f"No hay colecciones construidas para {tipo!r} en {dir_cols}. "
            f"Ejecuta primero el script de dataset con --ingestar."
        )
    if n_pedido in disponibles:
        return n_pedido
    menores = [t for t in disponibles if t <= n_pedido]
    return max(menores) if menores else min(disponibles)


def _cargar_metadatos_imagenes() -> dict[str, dict]:
    meta = {}
    ruta_etq = DIR_AMAZON_BENCH / "etiquetas.json"
    etiquetas = {}
    if ruta_etq.exists():
        with open(ruta_etq, "r", encoding="utf-8") as f:
            etiquetas = json.load(f)

    ruta_manifiesto = BENCH_DIR / "datasets" / "ids" / "amazon_img_ids.csv"
    if ruta_manifiesto.exists():
        with open(ruta_manifiesto, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                pid = str(row["id"])
                meta[pid] = {
                    "id": pid,
                    "asin": row.get("asin", ""),
                    "categoria": row.get("categoria") or etiquetas.get(pid, "Electronics"),
                    "titulo": row.get("titulo", ""),
                    "ruta": "",
                }

    for nombre_csv in ("objetos.csv", "consultas.csv"):
        ruta_csv = DIR_AMAZON_BENCH / nombre_csv
        if ruta_csv.exists():
            with open(ruta_csv, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    pid = str(row["id"])
                    actual = meta.get(pid, {"id": pid, "asin": "", "categoria": etiquetas.get(pid, "Electronics"), "titulo": ""})
                    actual["ruta"] = row.get("ruta", actual.get("ruta", ""))
                    if row.get("categoria"):
                        actual["categoria"] = row["categoria"]
                    if row.get("titulo"):
                        actual["titulo"] = row["titulo"]
                    meta[pid] = actual
    return meta


def _cargar_metadatos_audio() -> dict[str, dict]:
    meta = {}
    ruta_etq = DIR_FMA / "etiquetas.json"
    etiquetas = {}
    if ruta_etq.exists():
        with open(ruta_etq, "r", encoding="utf-8") as f:
            etiquetas = json.load(f)

    for nombre_csv in ("segmentos.csv", "consultas.csv"):
        ruta_csv = DIR_FMA / nombre_csv
        if ruta_csv.exists():
            with open(ruta_csv, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    tid = str(row["track_id"])
                    if tid not in meta:
                        meta[tid] = {
                            "track_id": tid,
                            "genero": row.get("genero") or etiquetas.get(tid, "Unknown"),
                            "titulo": row.get("titulo") or f"Track {tid}",
                            "artista": row.get("artista") or "Unknown Artist",
                            "ruta": row.get("ruta", ""),
                        }
    return meta


def evaluar_galeria_imagenes(n_pedido: int, num_consultas: int = 50, k: int = 5) -> dict:
    n_col = _resolver_n_disponible("imagen", n_pedido)
    vectores_base, ids_base = bovw.cargar_coleccion("imagen", n_col)
    ids_str = [str(oid) for oid in ids_base]
    meta_por_id = _cargar_metadatos_imagenes()

    # Construir conjunto de consultas: primero desde consultas.csv y complementar con elementos de la coleccion
    candidatos_q = []
    ruta_cons = DIR_AMAZON_BENCH / "consultas.csv"
    if ruta_cons.exists():
        with open(ruta_cons, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                pid = str(row["id"])
                ruta_img = row.get("ruta", "")
                if os.path.exists(ruta_img):
                    candidatos_q.append({
                        "id": pid,
                        "ruta": ruta_img,
                        "categoria": row.get("categoria") or meta_por_id.get(pid, {}).get("categoria", "Electronics"),
                        "titulo": row.get("titulo") or meta_por_id.get(pid, {}).get("titulo", ""),
                        "en_base": False,
                        "idx_base": -1,
                    })

    # Agregar tambien consultas de categorias frecuentes presentes en la base (excluyendo el propio id al buscar)
    conteo_cats = {}
    for pid in ids_str:
        cat = meta_por_id.get(pid, {}).get("categoria", "Electronics")
        conteo_cats[cat] = conteo_cats.get(cat, 0) + 1

    for idx_b, pid in enumerate(ids_str):
        info = meta_por_id.get(pid, {})
        cat = info.get("categoria", "Electronics")
        ruta_img = info.get("ruta", "")
        if conteo_cats.get(cat, 0) >= 8 and os.path.exists(ruta_img):
            candidatos_q.append({
                "id": pid,
                "ruta": ruta_img,
                "categoria": cat,
                "titulo": info.get("titulo", ""),
                "en_base": True,
                "idx_base": idx_b,
            })
        if len(candidatos_q) >= num_consultas * 2:
            break

    # Extraer o tomar vectores de consulta
    consultas_validas = []
    vectores_q = []
    for item in candidatos_q[: max(num_consultas, 80)]:
        try:
            if item["en_base"] and 0 <= item["idx_base"] < len(vectores_base):
                vec = vectores_base[item["idx_base"]]
            else:
                vec = bovw.ExtractFeatures(item["ruta"], tipo="imagen", n_coleccion=n_col)
            if np.any(vec > 0):
                consultas_validas.append(item)
                vectores_q.append(vec.astype(np.float32))
        except Exception:
            continue
        if len(consultas_validas) >= max(num_consultas, 70):
            break

    matriz_q = np.vstack(vectores_q)
    resultados_por_metrica = {}

    for metrica in METRICAS:
        pos_lote, dist_lote = knn_exacto_lote(matriz_q, vectores_base, k + 2, metrica)
        evaluaciones = []
        for i, q_info in enumerate(consultas_validas):
            vecinos = []
            for p_idx, dist_val in zip(pos_lote[i].tolist(), dist_lote[i].tolist()):
                pid_vec = ids_str[p_idx]
                if pid_vec == q_info["id"]:
                    continue
                m_vec = meta_por_id.get(pid_vec, {})
                cat_vec = m_vec.get("categoria", "Electronics")
                vecinos.append({
                    "rank": len(vecinos) + 1,
                    "id": pid_vec,
                    "categoria": cat_vec,
                    "titulo": m_vec.get("titulo", ""),
                    "ruta": m_vec.get("ruta", ""),
                    "distancia": round(float(dist_val), 4),
                    "coincide": cat_vec == q_info["categoria"],
                })
                if len(vecinos) >= k:
                    break

            aciertos = sum(1 for v in vecinos if v["coincide"])
            evaluaciones.append({
                "consulta": {
                    "id": q_info["id"],
                    "categoria": q_info["categoria"],
                    "titulo": q_info["titulo"],
                    "ruta": q_info["ruta"],
                },
                "metrica": metrica,
                "aciertos_top5": aciertos,
                "precision_top5": round(aciertos / float(k), 4),
                "vecinos": vecinos,
            })

        # Ordenar para elegir los mejores exitos y los errores mas claros
        exitos = sorted(
            [e for e in evaluaciones if os.path.exists(e["consulta"]["ruta"])],
            key=lambda e: (e["aciertos_top5"], -e["vecinos"][0]["distancia"] if e["vecinos"] else 0.0),
            reverse=True,
        )
        errores = sorted(
            [e for e in evaluaciones if e["aciertos_top5"] == 0 and os.path.exists(e["consulta"]["ruta"])],
            key=lambda e: e["vecinos"][0]["distancia"] if e["vecinos"] else 999.0,
        )
        if not errores:
            errores = sorted(evaluaciones, key=lambda e: e["aciertos_top5"])

        resultados_por_metrica[metrica] = {
            "num_consultas": min(num_consultas, len(evaluaciones)),
            "precision_media_top5": round(
                float(np.mean([e["precision_top5"] for e in evaluaciones[:num_consultas]])), 4
            ),
            "candidatos_exito": exitos[:5],
            "candidatos_error": errores[:5],
            "todas": evaluaciones[:num_consultas],
        }

    return {"n_coleccion": n_col, "k": k, "metricas": resultados_por_metrica}


def evaluar_galeria_audio(n_pedido: int, num_consultas: int = 50, k: int = 5) -> dict:
    n_col = _resolver_n_disponible("audio", n_pedido)
    vectores_base, ids_base = bovw.cargar_coleccion("audio", n_col)
    meta_tracks = _cargar_metadatos_audio()

    # Normalizar ids de la base: cada elemento es (track_id, seg_idx)
    info_base = []
    for oid in ids_base:
        if isinstance(oid, (tuple, list)) and len(oid) >= 2:
            tid_str, seg_idx = str(oid[0]), int(oid[1])
        else:
            tid_str, seg_idx = str(oid), 0
        m = meta_tracks.get(tid_str, {})
        info_base.append({
            "track_id": tid_str,
            "segmento": seg_idx,
            "seg_inicio": round(seg_idx * mm_config.SEG_S, 2),
            "seg_fin": round((seg_idx + 1) * mm_config.SEG_S, 2),
            "genero": m.get("genero", "Unknown"),
            "titulo": m.get("titulo", f"Track {tid_str}"),
            "artista": m.get("artista", "Unknown"),
            "ruta": m.get("ruta", ""),
        })

    candidatos_q = []
    ruta_cons = DIR_FMA / "consultas.csv"
    if ruta_cons.exists():
        with open(ruta_cons, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                tid = str(row["track_id"])
                seg = int(row.get("segmento", 0))
                ruta_mp3 = row.get("ruta", "")
                if os.path.exists(ruta_mp3):
                    candidatos_q.append({
                        "track_id": tid,
                        "segmento": seg,
                        "seg_inicio": float(row.get("seg_inicio", seg * mm_config.SEG_S)),
                        "seg_fin": float(row.get("seg_fin", (seg + 1) * mm_config.SEG_S)),
                        "genero": row.get("genero") or meta_tracks.get(tid, {}).get("genero", "Unknown"),
                        "titulo": row.get("titulo") or meta_tracks.get(tid, {}).get("titulo", f"Track {tid}"),
                        "artista": row.get("artista") or meta_tracks.get(tid, {}).get("artista", ""),
                        "ruta": ruta_mp3,
                        "en_base": False,
                        "idx_base": -1,
                    })

    # Agregar tambien segmentos de distintas pistas de la base (buscando en pistas diferentes para evaluar genero)
    vistos_tracks = set()
    for idx_b, b_info in enumerate(info_base):
        tid = b_info["track_id"]
        if tid not in vistos_tracks and b_info["genero"] != "Unknown":
            vistos_tracks.add(tid)
            candidatos_q.append({
                **b_info,
                "en_base": True,
                "idx_base": idx_b,
            })
        if len(candidatos_q) >= num_consultas * 2:
            break

    consultas_validas = []
    vectores_q = []
    for item in candidatos_q[: max(num_consultas, 80)]:
        try:
            if item["en_base"] and 0 <= item["idx_base"] < len(vectores_base):
                vec = vectores_base[item["idx_base"]]
            else:
                vec = bovw.ExtractFeatures(
                    item["ruta"], tipo="audio", n_coleccion=n_col, segmento=int(item["segmento"])
                )
            if np.any(vec > 0):
                consultas_validas.append(item)
                vectores_q.append(vec.astype(np.float32))
        except Exception:
            continue
        if len(consultas_validas) >= max(num_consultas, 70):
            break

    matriz_q = np.vstack(vectores_q)
    resultados_por_metrica = {}

    for metrica in METRICAS:
        pos_lote, dist_lote = knn_exacto_lote(matriz_q, vectores_base, k + 20, metrica)
        evaluaciones = []
        for i, q_info in enumerate(consultas_validas):
            vecinos = []
            for p_idx, dist_val in zip(pos_lote[i].tolist(), dist_lote[i].tolist()):
                b_vec = info_base[p_idx]
                # Evitar devolver exactamente el mismo segmento si la consulta salio de la base
                if b_vec["track_id"] == q_info["track_id"] and b_vec["segmento"] == q_info["segmento"]:
                    continue
                vecinos.append({
                    "rank": len(vecinos) + 1,
                    "track_id": b_vec["track_id"],
                    "segmento": b_vec["segmento"],
                    "seg_inicio": b_vec["seg_inicio"],
                    "seg_fin": b_vec["seg_fin"],
                    "genero": b_vec["genero"],
                    "titulo": b_vec["titulo"],
                    "artista": b_vec["artista"],
                    "distancia": round(float(dist_val), 4),
                    "misma_pista": b_vec["track_id"] == q_info["track_id"],
                    "coincide": b_vec["genero"] == q_info["genero"],
                })
                if len(vecinos) >= k:
                    break

            aciertos = sum(1 for v in vecinos if v["coincide"])
            evaluaciones.append({
                "consulta": {
                    "track_id": q_info["track_id"],
                    "segmento": q_info["segmento"],
                    "seg_inicio": q_info["seg_inicio"],
                    "seg_fin": q_info["seg_fin"],
                    "genero": q_info["genero"],
                    "titulo": q_info["titulo"],
                    "artista": q_info["artista"],
                },
                "metrica": metrica,
                "aciertos_top5": aciertos,
                "precision_top5": round(aciertos / float(k), 4),
                "vecinos": vecinos,
            })

        exitos = sorted(
            evaluaciones,
            key=lambda e: (e["aciertos_top5"], -e["vecinos"][0]["distancia"] if e["vecinos"] else 0.0),
            reverse=True,
        )
        errores = sorted(
            [e for e in evaluaciones if e["aciertos_top5"] == 0],
            key=lambda e: e["vecinos"][0]["distancia"] if e["vecinos"] else 999.0,
        )
        if not errores:
            errores = sorted(evaluaciones, key=lambda e: e["aciertos_top5"])

        resultados_por_metrica[metrica] = {
            "num_consultas": min(num_consultas, len(evaluaciones)),
            "precision_media_top5": round(
                float(np.mean([e["precision_top5"] for e in evaluaciones[:num_consultas]])), 4
            ),
            "candidatos_exito": exitos[:5],
            "candidatos_error": errores[:5],
            "todas": evaluaciones[:num_consultas],
        }

    return {"n_coleccion": n_col, "k": k, "metricas": resultados_por_metrica}


def _cargar_rgb(ruta: str, lado: int = 220) -> np.ndarray:
    if os.path.exists(ruta):
        datos = np.fromfile(ruta, dtype=np.uint8)
        bgr = cv2.imdecode(datos, cv2.IMREAD_COLOR)
        if bgr is not None:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            escala = min(lado / max(1, w), lado / max(1, h))
            nw, nh = max(1, int(round(w * escala))), max(1, int(round(h * escala)))
            redim = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
            lienzo = np.full((lado, lado, 3), 255, dtype=np.uint8)
            y0 = (lado - nh) // 2
            x0 = (lado - nw) // 2
            lienzo[y0 : y0 + nh, x0 : x0 + nw] = redim
            return lienzo
    return np.full((lado, lado, 3), 240, dtype=np.uint8)


def _recortar_texto(texto: str, max_chars: int = 22) -> str:
    texto = (texto or "").strip()
    return texto if len(texto) <= max_chars else texto[: max_chars - 1] + "…"


def renderizar_galeria_imagenes(datos_img: dict, ruta_png: Path) -> None:
    filas_casos = [
        ("ÉXITO — Coseno", datos_img["metricas"]["cosine"]["candidatos_exito"][0]),
        ("ÉXITO — Euclidiana", datos_img["metricas"]["euclidean"]["candidatos_exito"][0]),
        ("ERROR — Coseno", datos_img["metricas"]["cosine"]["candidatos_error"][0]),
        ("ERROR — Euclidiana", datos_img["metricas"]["euclidean"]["candidatos_error"][0]),
    ]

    fig, axes = plt.subplots(4, 6, figsize=(16, 11), dpi=160)
    fig.suptitle(
        "Galería Visual k-NN (Top-5) en Imágenes Amazon — Casos de Éxito y Error (BoVW SIFT)",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    for fila_idx, (etiqueta_fila, caso) in enumerate(filas_casos):
        q = caso["consulta"]
        ax_q = axes[fila_idx, 0]
        ax_q.imshow(_cargar_rgb(q["ruta"]))
        ax_q.set_xticks([])
        ax_q.set_yticks([])
        for spine in ax_q.spines.values():
            spine.set_edgecolor("#1d4ed8")
            spine.set_linewidth(3.0)
        ax_q.set_title(
            f"{etiqueta_fila}\nConsulta (ID {q['id']})\n[{_recortar_texto(q['categoria'], 20)}]",
            fontsize=8.5,
            fontweight="bold",
            color="#1e3a8a",
        )
        ax_q.set_xlabel(f"Aciertos: {caso['aciertos_top5']}/5", fontsize=8, fontweight="bold")

        for col_idx in range(1, 6):
            ax = axes[fila_idx, col_idx]
            ax.set_xticks([])
            ax.set_yticks([])
            if col_idx - 1 < len(caso["vecinos"]):
                v = caso["vecinos"][col_idx - 1]
                ax.imshow(_cargar_rgb(v["ruta"]))
                color_borde = "#16a34a" if v["coincide"] else "#dc2626"
                simbolo = "✓" if v["coincide"] else "✗"
                for spine in ax.spines.values():
                    spine.set_edgecolor(color_borde)
                    spine.set_linewidth(2.5)
                ax.set_title(
                    f"#{v['rank']} {simbolo} d={v['distancia']:.3f}\n[{_recortar_texto(v['categoria'], 20)}]",
                    fontsize=8,
                    color=color_borde,
                    fontweight="bold",
                )
                ax.set_xlabel(_recortar_texto(v["titulo"], 24), fontsize=7.5, color="#374151")
            else:
                ax.axis("off")

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    ruta_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta_png, bbox_inches="tight")
    plt.close(fig)


def generar_reporte_galeria_md(datos_img: dict, datos_aud: dict, ruta_md: Path) -> None:
    lineas = [
        "# Galería de Casos de Éxito y Error — Parte 4: Búsqueda Multimedia (k-NN Exacto, $k=5$)",
        "",
        "## 1. Resumen de Precisión Cualitativa Top-5 (`euclidean` vs `cosine`)",
        "",
        "| Dominio | Colección ($N$) | Consultas Evaluadas | Precisión@5 Media (`euclidean`) | Precisión@5 Media (`cosine`) |",
        "|:---|---:|---:|---:|---:|",
        f"| **Imágenes (Amazon SIFT BoVW)** | {datos_img['n_coleccion']:,} | {datos_img['metricas']['cosine']['num_consultas']} | "
        f"{datos_img['metricas']['euclidean']['precision_media_top5']:.3f} | {datos_img['metricas']['cosine']['precision_media_top5']:.3f} |",
        f"| **Audio (FMA MFCC BoAW)** | {datos_aud['n_coleccion']:,} | {datos_aud['metricas']['cosine']['num_consultas']} | "
        f"{datos_aud['metricas']['euclidean']['precision_media_top5']:.3f} | {datos_aud['metricas']['cosine']['precision_media_top5']:.3f} |",
        "",
        "---",
        "",
        "## 2. Galería de Imágenes (Amazon Electronics)",
        "",
        f"La cuadrícula visual completa se encuentra generada en [`galeria_imagenes.png`](file://{PNG_GALERIA_IMG}).",
        "",
    ]

    for metrica in METRICAS:
        exito = datos_img["metricas"][metrica]["candidatos_exito"][0]
        error = datos_img["metricas"][metrica]["candidatos_error"][0]
        q_ok = exito["consulta"]
        q_err = error["consulta"]

        lineas.extend([
            f"### 2.{1 if metrica == 'euclidean' else 2} Métrica `{metrica}` — Imágenes",
            "",
            f"- **Caso de Éxito ({exito['aciertos_top5']}/5 aciertos):** Consulta `ID {q_ok['id']}` — Categoría **`{q_ok['categoria']}`** (*{_recortar_texto(q_ok['titulo'], 70)}*)",
            "",
            "| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |",
            "|---:|---:|:---|:---|---:|:---:|",
        ])
        for v in exito["vecinos"]:
            lineas.append(
                f"| #{v['rank']} | `{v['id']}` | `{v['categoria']}` | {_recortar_texto(v['titulo'], 55)} | {v['distancia']:.4f} | {'Sí' if v['coincide'] else 'No'} |"
            )

        lineas.extend([
            "",
            f"- **Caso de Error ({error['aciertos_top5']}/5 aciertos):** Consulta `ID {q_err['id']}` — Categoría **`{q_err['categoria']}`** (*{_recortar_texto(q_err['titulo'], 70)}*)",
            "",
            "| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |",
            "|---:|---:|:---|:---|---:|:---:|",
        ])
        for v in error["vecinos"]:
            lineas.append(
                f"| #{v['rank']} | `{v['id']}` | `{v['categoria']}` | {_recortar_texto(v['titulo'], 55)} | {v['distancia']:.4f} | {'Sí' if v['coincide'] else 'No'} |"
            )
        lineas.append("")

    lineas.extend([
        "### Explicación Técnica de los Casos de Error en Imágenes (BoVW SIFT)",
        "1. **Pérdida de geometría global (Bag-of-Words sin verificación espacial):** El histograma BoVW cuantiza parches locales de gradiente SIFT de $128\\text{D}$ ignorando dónde aparecen en la imagen. Por ello, objetos rectangulares oscuros sobre fondo blanco (p. ej., un disco duro externo, una batería portátil, un estuche o una tarjeta capturadora) comparten las mismas esquinas y bordes de alto contraste, activando las mismas *visual words* aunque pertenezcan a subcategorías distintas.",
        "2. **Invarianza al color (escala de grises):** SIFT opera sobre luminancia; dos productos con idéntica textura metálica o malla (como un micrófono y un parlante Bluetooth) generan descriptores locales casi indistinguibles.",
        "",
        "---",
        "",
        "## 3. Galería de Audio (FMA — Segmentos de 2.0 s con MFCC BoAW)",
        "",
    ])

    for metrica in METRICAS:
        exito = datos_aud["metricas"][metrica]["candidatos_exito"][0]
        error = datos_aud["metricas"][metrica]["candidatos_error"][0]
        q_ok = exito["consulta"]
        q_err = error["consulta"]

        lineas.extend([
            f"### 3.{1 if metrica == 'euclidean' else 2} Métrica `{metrica}` — Audio",
            "",
            f"- **Caso de Éxito ({exito['aciertos_top5']}/5 aciertos):** Pista `{q_ok['track_id']}` seg `{q_ok['segmento']}` (`{q_ok['seg_inicio']:.1f}-{q_ok['seg_fin']:.1f}s`) — Género **`{q_ok['genero']}`** (*{q_ok['titulo']}* — {q_ok['artista']})",
            "",
            "| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |",
            "|---:|---:|---:|:---:|:---|:---|---:|:---:|",
        ])
        for v in exito["vecinos"]:
            lineas.append(
                f"| #{v['rank']} | `{v['track_id']}` | `{v['segmento']}` | `{v['seg_inicio']:.1f}-{v['seg_fin']:.1f}s` | "
                f"`{v['genero']}` | {_recortar_texto(v['titulo'], 35)} — {_recortar_texto(v['artista'], 25)} | "
                f"{v['distancia']:.4f} | {'Sí' if v['coincide'] else 'No'} |"
            )

        lineas.extend([
            "",
            f"- **Caso de Error ({error['aciertos_top5']}/5 aciertos):** Pista `{q_err['track_id']}` seg `{q_err['segmento']}` (`{q_err['seg_inicio']:.1f}-{q_err['seg_fin']:.1f}s`) — Género **`{q_err['genero']}`** (*{q_err['titulo']}* — {q_err['artista']})",
            "",
            "| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |",
            "|---:|---:|---:|:---:|:---|:---|---:|:---:|",
        ])
        for v in error["vecinos"]:
            lineas.append(
                f"| #{v['rank']} | `{v['track_id']}` | `{v['segmento']}` | `{v['seg_inicio']:.1f}-{v['seg_fin']:.1f}s` | "
                f"`{v['genero']}` | {_recortar_texto(v['titulo'], 35)} — {_recortar_texto(v['artista'], 25)} | "
                f"{v['distancia']:.4f} | {'Sí' if v['coincide'] else 'No'} |"
            )
        lineas.append("")

    lineas.extend([
        "### Explicación Técnica de los Casos de Error en Audio (BoAW MFCC)",
        "1. **Similitud tímbrica instantánea entre géneros distintos:** Los coeficientes MFCC ($c_1 \\dots c_{19}$) describen la envolvente espectral de corto plazo (timbre/instrumentación en ventanas de ~93 ms). Cuando un segmento de 2 segundos contiene solo una introducción acústica, un pasaje vocal o percusión aislada, una pista de *Folk*, *Pop* o *Indie-Rock* presenta la misma huella espectral.",
        "2. **Ausencia de orden temporal y BPM en el histograma:** El modelo Bag-of-Audio-Words resume las 87 tramas del segmento de 2 s en un histograma estático de frecuencias de *audio words*, excelente para identificar fragmentos de la misma grabación (detección de copyright) o texturas instrumentales densas, pero ciego a la progresión armónica de largo plazo.",
        "",
    ])

    ruta_md.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--tamanos", nargs="+", default=["1k"],
                        help="Tamaño de colección sobre el cual armar la galería (por defecto: 1k)")
    parser.add_argument("--consultas", type=int, default=50,
                        help="Cantidad de consultas a correr por dominio (~50 por defecto)")
    parser.add_argument("--k", type=int, default=5,
                        help="Top-k vecinos para la galería (por defecto: 5)")
    args = parser.parse_args(argv)

    n_pedido = max(parsear_tamanos(args.tamanos))
    print(f"[galeria] Evaluando ~{args.consultas} consultas con k={args.k} (N objetivo={n_pedido:,}) ...")

    datos_img = evaluar_galeria_imagenes(n_pedido, num_consultas=args.consultas, k=args.k)
    datos_aud = evaluar_galeria_audio(n_pedido, num_consultas=args.consultas, k=args.k)

    salida_total = {
        "imagen": datos_img,
        "audio": datos_aud,
    }
    DIR_RESULTS.mkdir(parents=True, exist_ok=True)
    with open(JSON_GALERIA, "w", encoding="utf-8") as f:
        json.dump(salida_total, f, ensure_ascii=False, indent=2)

    renderizar_galeria_imagenes(datos_img, PNG_GALERIA_IMG)
    generar_reporte_galeria_md(datos_img, datos_aud, MD_GALERIA_AUDIO)

    print(
        f"[galeria] Galería completada:\n"
        f"  - JSON:   {JSON_GALERIA}\n"
        f"  - Imagen: {PNG_GALERIA_IMG}\n"
        f"  - Audio:  {MD_GALERIA_AUDIO}"
    )


if __name__ == "__main__":
    main()
