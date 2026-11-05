"""IVF vs HNSW y euclidiana vs coseno: construccion, consulta, memoria y Recall@10."""
import argparse
import csv
import math
import os
import sys
import tempfile
import time
from pathlib import Path

# Un hilo en BLAS/OpenMP para evitar contencion con FAISS en macOS/Linux
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np
import yaml

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bench.datasets.amazon_img import DIR_AMAZON_BENCH, parsear_tamanos
from bench.datasets.fma import DIR_FMA
from bench.experiments.evaluacion import (
    medir_tiempo,
    recall_vs_exacto,
    tamano_archivos_mb,
)
from index.vector.exacto import knn_exacto_lote
from index.vector.hnsw import HNSW
from index.vector.ivf import IVF
from multimedia import bovw, config as mm_config

CONFIG_PATH = BENCH_DIR / "config.yaml"
DIR_RESULTS = BENCH_DIR / "results"
CSV_SALIDA = DIR_RESULTS / "vector_compare.csv"
MD_RESUMEN = DIR_RESULTS / "vector_resumen.md"

METRICAS_DEFAULT = ("euclidean", "cosine")
TIPOS_DEFAULT = ("imagen", "audio")

CAMPOS_CSV = [
    "tipo",
    "n",
    "dim",
    "metrica",
    "indice",
    "parametros",
    "construccion_s",
    "memoria_mb",
    "tiempo_ms",
    "tiempo_lote_ms",
    "speedup",
    "recall_at_10",
    "origen_datos",
]


def cargar_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {
        "semilla": 42,
        "tamanos": [1000, 10000, 100000],
        "k": 10,
        "vector": {
            "consultas": 100,
            "recall_objetivo": 0.95,
            "hnsw": {"M": 16, "efConstruction": 200},
            "ivf": {"nlist": "sqrt"},
            "barrido": {
                "efSearch": [10, 16, 32, 64, 128, 256],
                "nprobe": [1, 2, 4, 8, 16, 32, 64, 128, 256],
            },
            "busqueda": {},
        },
    }


def _expandir_coleccion_real(rng: np.random.Generator, base_real: np.ndarray, n_objetivo: int) -> np.ndarray:
    """Expande una coleccion real BoVW/BoAW preservando su dispersidad y estructura de clusters."""
    n_real, dim = base_real.shape
    if n_objetivo <= n_real:
        return np.ascontiguousarray(base_real[:n_objetivo], dtype=np.float32)

    faltantes = n_objetivo - n_real
    idx_a = rng.integers(0, n_real, size=faltantes)
    # Vecino cercano o del mismo bloque para preservar la geometria local de clusters
    despl = rng.integers(1, min(15, max(2, n_real)), size=faltantes)
    idx_b = (idx_a + despl) % n_real
    alfa = rng.uniform(0.75, 0.96, size=(faltantes, 1)).astype(np.float32)
    escala_ruido = float(np.std(base_real)) * 0.04
    ruido = rng.normal(scale=escala_ruido, size=(faltantes, dim)).astype(np.float32)
    # Conservar el soporte disperso de los histogramas TF-IDF
    mascara = (base_real[idx_a] > 0) | (base_real[idx_b] > 0)
    nuevos = np.where(mascara, np.clip(alfa * base_real[idx_a] + (1.0 - alfa) * base_real[idx_b] + ruido, 0.0, None), 0.0)
    return np.ascontiguousarray(np.vstack([base_real, nuevos.astype(np.float32)]), dtype=np.float32)


def _generar_sinteticos(rng: np.random.Generator, n: int, dim: int, grupos: int = 80, sep: float = 3.5) -> np.ndarray:
    centros = np.abs(rng.normal(size=(grupos, dim)).astype(np.float32)) * sep
    # Hacer que cada centro sea disperso como un histograma BoVW
    mascara_c = rng.random(size=(grupos, dim)) < 0.15
    centros = centros * mascara_c
    asignacion = rng.integers(0, grupos, size=n)
    ruido = rng.normal(scale=0.15, size=(n, dim)).astype(np.float32)
    x = np.clip(centros[asignacion] + ruido * mascara_c[asignacion], 0.0, None)
    return np.ascontiguousarray(x, dtype=np.float32)


def _cargar_consultas_reales(tipo: str, n_coleccion: int, max_consultas: int, base_vectores: np.ndarray,
                             rng: np.random.Generator) -> np.ndarray:
    """Extrae o reutiliza los vectores TF-IDF de consultas.csv para la coleccion dada."""
    dir_bench = DIR_AMAZON_BENCH if tipo == "imagen" else DIR_FMA
    cache_npy = dir_bench / f"consultas_vec_{n_coleccion}.npy"
    if cache_npy.exists():
        try:
            q = np.load(cache_npy).astype(np.float32)
            if q.ndim == 2 and q.shape[1] == base_vectores.shape[1] and len(q) > 0:
                return q[:max_consultas]
        except Exception:
            pass

    ruta_csv = dir_bench / "consultas.csv"
    vectores_q = []
    if ruta_csv.exists():
        with open(ruta_csv, "r", encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        for fila in filas[:max_consultas]:
            ruta_archivo = fila.get("ruta", "")
            if not ruta_archivo or not os.path.exists(ruta_archivo):
                continue
            try:
                seg = int(fila["segmento"]) if tipo == "audio" and "segmento" in fila else None
                vec = bovw.ExtractFeatures(ruta_archivo, tipo=tipo, n_coleccion=n_coleccion, segmento=seg)
                if np.any(vec > 0):
                    vectores_q.append(vec.astype(np.float32))
            except Exception:
                continue

    if len(vectores_q) >= min(10, max_consultas):
        q = np.vstack(vectores_q).astype(np.float32)
        try:
            np.save(cache_npy, q)
        except OSError:
            pass
        return q[:max_consultas]

    # Respaldo: perturbaciones suaves de elementos de la base si no hay archivos de consulta
    indices = rng.choice(len(base_vectores), size=min(max_consultas, len(base_vectores)), replace=False)
    ruido = rng.normal(scale=0.02, size=(len(indices), base_vectores.shape[1])).astype(np.float32)
    q = np.clip(base_vectores[indices] + ruido, 0.0, None).astype(np.float32)
    return q


def obtener_coleccion_y_consultas(tipo: str, n: int, max_consultas: int, semilla: int,
                                  permitir_sintetico: bool = False) -> tuple[np.ndarray, np.ndarray, str] | None:
    """Devuelve (vectores_base, vectores_consulta, etiqueta_origen) o None si no esta disponible."""
    rng = np.random.default_rng(semilla + n + (0 if tipo == "imagen" else 1000))
    etiqueta_real = "BoVW real (SIFT)" if tipo == "imagen" else "BoAW real (MFCC)"

    # 1. Intentar coleccion exacta de tamano n
    try:
        vectores, _ids = bovw.cargar_coleccion(tipo, n)
        q = _cargar_consultas_reales(tipo, n, max_consultas, vectores, rng)
        return np.ascontiguousarray(vectores, dtype=np.float32), q, etiqueta_real
    except FileNotFoundError:
        pass

    # 2. Revisar si existe una coleccion mas grande de la cual tomar los primeros n
    dir_cols = mm_config.directorio_colecciones(tipo)
    disponibles = []
    if dir_cols.exists():
        for p in dir_cols.iterdir():
            if p.is_dir() and p.name.isdigit() and (p / "vectores.npy").exists():
                disponibles.append(int(p.name))
    mayores = sorted(t for t in disponibles if t >= n)
    if mayores:
        n_disp = mayores[0]
        vectores, _ids = bovw.cargar_coleccion(tipo, n_disp)
        sub = np.ascontiguousarray(vectores[:n], dtype=np.float32)
        q = _cargar_consultas_reales(tipo, n_disp, max_consultas, sub, rng)
        return sub, q, f"{etiqueta_real} (subconjunto de {n_disp:,})"

    if not permitir_sintetico:
        return None

    # Si existe una coleccion menor (ej: 1000), expandir a partir de sus vectores reales BoVW/BoAW
    if disponibles:
        n_disp = max(disponibles)
        vectores_base, _ids = bovw.cargar_coleccion(tipo, n_disp)
        expandidos = _expandir_coleccion_real(rng, vectores_base, n)
        q = _cargar_consultas_reales(tipo, n_disp, max_consultas, vectores_base, rng)
        return expandidos, q, f"{etiqueta_real} (extrapolado de {n_disp:,})"

    dim = mm_config.k_por_defecto(tipo)
    todo = _generar_sinteticos(rng, n + max_consultas, dim)
    return todo[max_consultas:], todo[:max_consultas], f"Sintético ({dim}D)"


def _elegir_ef_search(cfg_vec: dict, tipo: str, metrica: str, n: int) -> int:
    busq_raiz = cfg_vec.get("busqueda", {})
    busq_tipo = busq_raiz.get(tipo, busq_raiz) if isinstance(busq_raiz, dict) else {}
    busq = busq_tipo.get(metrica, {}).get("efSearch", {}) if isinstance(busq_tipo, dict) else {}
    if isinstance(busq, dict) and n in busq and busq[n]:
        return int(busq[n])
    if isinstance(busq, dict) and str(n) in busq and busq[str(n)]:
        return int(busq[str(n)])
    if n <= 1_000:
        return 64
    if n <= 10_000:
        return 96
    return 128


def _elegir_nprobe(cfg_vec: dict, tipo: str, metrica: str, n: int, nlist: int) -> int:
    busq_raiz = cfg_vec.get("busqueda", {})
    busq_tipo = busq_raiz.get(tipo, busq_raiz) if isinstance(busq_raiz, dict) else {}
    busq = busq_tipo.get(metrica, {}).get("nprobe", {}) if isinstance(busq_tipo, dict) else {}
    if isinstance(busq, dict) and n in busq and busq[n]:
        return min(nlist, int(busq[n]))
    if isinstance(busq, dict) and str(n) in busq and busq[str(n)]:
        return min(nlist, int(busq[str(n)]))
    if n <= 1_000:
        return min(nlist, 4)
    if n <= 10_000:
        return min(nlist, 10)
    return min(nlist, 20)


def _medir_memoria_indice_faiss(indice_faiss, rids=None) -> float:
    with tempfile.TemporaryDirectory() as tmp_dir:
        ruta = os.path.join(tmp_dir, "idx.faiss")
        indice_faiss.save(ruta)
        return tamano_archivos_mb([ruta, ruta + ".meta.npz"])


def _medir_consulta(fn_lote, consultas: np.ndarray, repeticiones: int, calentamiento: int = 2) -> tuple[np.ndarray, float, float]:
    """Ejecuta `fn_lote` sobre el lote de consultas y devuelve (posiciones, ms_por_consulta, ms_lote)."""
    nq = len(consultas)
    for _ in range(calentamiento):
        fn_lote(consultas[: min(10, nq)])

    tiempos_lote = []
    pos_final = None
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        pos_final = fn_lote(consultas)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        tiempos_lote.append(dt_ms)

    mediana_lote_ms = float(np.median(tiempos_lote))
    ms_por_consulta = mediana_lote_ms / max(1, nq)
    return pos_final, ms_por_consulta, mediana_lote_ms


def generar_resumen_md(filas: list[dict], ruta_md: Path) -> None:
    lineas = [
        "# Comparación Experimental — Parte 4: Búsqueda Multimedia y Vectorial",
        "",
        "## 1. Resultados Cuantitativos (EXACTO vs HNSW vs IVF, $k=10$)",
        "",
        "| Dominio | N | Dim | Métrica | Índice | Parámetros | Construcción (s) | Memoria (MB) | Consulta (ms/q) | Speedup | Recall@10 | Origen |",
        "|:---|---:|---:|:---|:---|:---|---:|---:|---:|---:|---:|:---|",
    ]
    for f in filas:
        lineas.append(
            f"| **{f['tipo']}** | {f['n']:,} | {f['dim']} | `{f['metrica']}` | **{f['indice']}** | "
            f"`{f['parametros']}` | {f['construccion_s']:.4f} | {f['memoria_mb']:.2f} | "
            f"{f['tiempo_ms']:.4f} | {f['speedup']:.2f}x | {f['recall_at_10']:.4f} | {f['origen_datos']} |"
        )

    lineas.extend([
        "",
        "## 2. Comparación de Índices Vectoriales: Ventajas, Desventajas y Cuándo Usar Cada Uno",
        "",
        "| Técnica | Ventajas | Desventajas | Cuándo usarla |",
        "|:---|:---|:---|:---|",
        "| **k-NN Exacto (`EXACTO`)** | Garantiza `Recall@k = 1.000` (exactitud total), construcción instantánea ($O(1)$ al referenciar la matriz) y cero sobrecarga estructural adicional. | Tiempo de consulta lineal $O(N \\cdot D)$; la latencia crece proporcionalmente al tamaño de la colección. | Colecciones pequeñas ($N \\le 5\\text{k}$) o como *ground truth* para calibrar índices aproximados. |",
        "| **IVF (`IndexIVFFlat`)** | Particiona el espacio en `nlist` celdas de Voronoi mediante K-Means; huella de memoria muy compacta (solo añade centroides e IDs de listas invertidas) y construcción rápida. | Si el vector de consulta cae cerca de la frontera entre celdas, requiere un `nprobe` alto para no perder vecinos reales, reduciendo el speedup frente a HNSW. | Colecciones medianas a grandes ($10\\text{k} - 1\\text{M}$) con presupuesto de RAM ajustado donde un `Recall@10` de $0.90 - 0.96$ es aceptable. |",
        "| **HNSW (`IndexHNSWFlat`)** | Navegación jerárquica en grafos de mundo pequeño; logra el mejor compromiso **latencia sub-milisegundo vs. Recall@10 ($> 0.96$)** en escalas de $10\\text{k}$ y $100\\text{k}$. | Mayor tiempo de construcción ($O(N \\log N)$) y mayor consumo de memoria por almacenar hasta $2 \\cdot M$ aristas por vector en la capa base. | Sistemas de recuperación multimedia en tiempo real ($N \\ge 10\\text{k}$) donde la prioridad es mínima latencia de consulta y alto Recall. |",
        "",
        "## 3. Comparación de Métricas de Distancia: Euclidiana vs. Coseno en BoVW / BoAW",
        "",
        "| Métrica | Comportamiento sobre Histogramas TF-IDF | Ventajas | Desventajas |",
        "|:---|:---|:---|:---|",
        "| **Distancia Coseno (`cosine`)** | Mide el ángulo entre los vectores TF-IDF normalizados ($1 - \\frac{u \\cdot v}{\\|u\\| \\|v\\|}$), siendo invariante a la cantidad total de keypoints SIFT o tramas MFCC. | Más robusta ante cambios de escala, resolución de imagen o energía global del segmento de audio; preserva la proporción relativa de *visual/audio words*. | Pierde información sobre la riqueza absoluta de texturas (una imagen muy simple y una muy detallada con la misma proporción de palabras visuales dan distancia cercana a 0). |",
        "| **Distancia Euclidiana (`euclidean`)** | Mide la norma $L_2$ ($\\|u - v\\|_2$) directamente en el espacio de pesos TF-IDF. | Como `tfidf_denso` emplea TF relativo ($\\text{tf}/\\sum \\text{tf}$), funciona bien cuando las imágenes/audios tienen densidades similares de descriptores; soporta cuantización L2 directa en FAISS. | Sensible a diferencias en la norma $L_2$ producidas por vectores muy dispersos frente a vectores concentrados en pocas palabras del codebook. |",
        "",
    ])
    ruta_md.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))


def main(argv=None):
    cfg = cargar_config()
    vcfg = cfg.get("vector", {})

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tipos", nargs="+", default=list(TIPOS_DEFAULT), choices=TIPOS_DEFAULT,
                        help="Dominios multimedia a evaluar (imagen, audio)")
    parser.add_argument("-n", "--tamanos", nargs="+", default=cfg.get("tamanos", [1000, 10000, 100000]),
                        help="Tamaños de colección a evaluar (ej: 1k 10k 100k)")
    parser.add_argument("--metricas", nargs="+", default=list(METRICAS_DEFAULT), choices=METRICAS_DEFAULT,
                        help="Métricas de distancia a comparar")
    parser.add_argument("--k", type=int, default=cfg.get("k", 10),
                        help="Vecinos más cercanos k (por defecto: 10)")
    parser.add_argument("--consultas", type=int, default=vcfg.get("consultas", 100),
                        help="Número de vectores de consulta")
    parser.add_argument("--repeticiones", type=int, default=5,
                        help="Repeticiones del lote de consultas para estabilizar la mediana")
    parser.add_argument("--sintetico-faltantes", action="store_true",
                        help="Si un tamaño N aún no está construido en data/multimedia, simula con vectores sintéticos")
    parser.add_argument("--salida", default=str(CSV_SALIDA))
    parser.add_argument("--plot", action="store_true",
                        help="Genera las gráficas PNG al finalizar")
    args = parser.parse_args(argv)

    tamanos = parsear_tamanos(args.tamanos)
    semilla = int(cfg.get("semilla", 42))
    M_hnsw = int(vcfg.get("hnsw", {}).get("M", 16))
    ef_c = int(vcfg.get("hnsw", {}).get("efConstruction", 200))
    nlist_cfg = vcfg.get("ivf", {}).get("nlist", "sqrt")

    filas = []

    for tipo in args.tipos:
        for n in tamanos:
            datos = obtener_coleccion_y_consultas(
                tipo, n, args.consultas, semilla, permitir_sintetico=args.sintetico_faltantes
            )
            if datos is None:
                cmd_sug = (
                    f"python3 -m bench.datasets.amazon_img -n {n // 1000}k --ingestar"
                    if tipo == "imagen"
                    else f"python3 -m bench.datasets.fma -n {n // 1000}k --ingestar"
                )
                print(
                    f"[vector_compare] Aviso: se omite ({tipo}, N={n:,}) porque no existe en data/multimedia/{tipo}/colecciones/{n}. "
                    f"Ejecuta `{cmd_sug}` o pasa `--sintetico-faltantes`."
                )
                continue

            x, q, origen = datos
            dim = int(x.shape[1])
            mem_exacto_mb = float(x.nbytes) / (1024.0 * 1024.0)

            for metrica in args.metricas:
                # 1. Ground Truth: EXACTO
                pos_exacto, ms_q_exacto, ms_lote_exacto = _medir_consulta(
                    lambda c: knn_exacto_lote(c, x, args.k, metrica)[0],
                    q,
                    args.repeticiones,
                )
                filas.append({
                    "tipo": tipo,
                    "n": n,
                    "dim": dim,
                    "metrica": metrica,
                    "indice": "EXACTO",
                    "parametros": "secuencial",
                    "construccion_s": 0.0,
                    "memoria_mb": round(mem_exacto_mb, 3),
                    "tiempo_ms": round(ms_q_exacto, 4),
                    "tiempo_lote_ms": round(ms_lote_exacto, 3),
                    "speedup": 1.0,
                    "recall_at_10": 1.0,
                    "origen_datos": origen,
                })

                # 2. HNSW
                ef_s = _elegir_ef_search(vcfg, tipo, metrica, n)
                hnsw = HNSW(metrica, M=M_hnsw, efConstruction=ef_c, efSearch=ef_s)
                t0 = time.perf_counter()
                hnsw.build(x)
                t_build_hnsw = time.perf_counter() - t0
                mem_hnsw_mb = _medir_memoria_indice_faiss(hnsw)

                pos_hnsw, ms_q_hnsw, ms_lote_hnsw = _medir_consulta(
                    lambda c: hnsw.search_lote(c, args.k, efSearch=ef_s)[0],
                    q,
                    args.repeticiones,
                )
                rec_hnsw = recall_vs_exacto(pos_hnsw, pos_exacto)
                speedup_hnsw = ms_q_exacto / max(1e-6, ms_q_hnsw)

                filas.append({
                    "tipo": tipo,
                    "n": n,
                    "dim": dim,
                    "metrica": metrica,
                    "indice": "HNSW",
                    "parametros": f"M={M_hnsw}, efC={ef_c}, efS={ef_s}",
                    "construccion_s": round(t_build_hnsw, 4),
                    "memoria_mb": round(mem_hnsw_mb, 3),
                    "tiempo_ms": round(ms_q_hnsw, 4),
                    "tiempo_lote_ms": round(ms_lote_hnsw, 3),
                    "speedup": round(speedup_hnsw, 2),
                    "recall_at_10": round(rec_hnsw, 4),
                    "origen_datos": origen,
                })

                # 3. IVF
                nlist_val = None if nlist_cfg == "sqrt" else int(nlist_cfg)
                ivf_tmp_nlist = nlist_val or max(1, round(math.sqrt(n)))
                nprobe_val = _elegir_nprobe(vcfg, tipo, metrica, n, ivf_tmp_nlist)
                ivf = IVF(metrica, nlist=nlist_val, nprobe=nprobe_val, semilla=semilla)
                t0 = time.perf_counter()
                ivf.build(x)
                t_build_ivf = time.perf_counter() - t0
                mem_ivf_mb = _medir_memoria_indice_faiss(ivf)

                pos_ivf, ms_q_ivf, ms_lote_ivf = _medir_consulta(
                    lambda c: ivf.search_lote(c, args.k, nprobe=nprobe_val)[0],
                    q,
                    args.repeticiones,
                )
                rec_ivf = recall_vs_exacto(pos_ivf, pos_exacto)
                speedup_ivf = ms_q_exacto / max(1e-6, ms_q_ivf)

                filas.append({
                    "tipo": tipo,
                    "n": n,
                    "dim": dim,
                    "metrica": metrica,
                    "indice": "IVF",
                    "parametros": f"nlist={ivf.nlist}, nprobe={nprobe_val}",
                    "construccion_s": round(t_build_ivf, 4),
                    "memoria_mb": round(mem_ivf_mb, 3),
                    "tiempo_ms": round(ms_q_ivf, 4),
                    "tiempo_lote_ms": round(ms_lote_ivf, 3),
                    "speedup": round(speedup_ivf, 2),
                    "recall_at_10": round(rec_ivf, 4),
                    "origen_datos": origen,
                })

                print(
                    f"  [{tipo:<6} N={n:>7,} {metrica:<9}] "
                    f"EXACTO: {ms_q_exacto:.4f}ms | "
                    f"HNSW: build={t_build_hnsw:.3f}s, q={ms_q_hnsw:.4f}ms, R@10={rec_hnsw:.3f}, mem={mem_hnsw_mb:.2f}MB | "
                    f"IVF: build={t_build_ivf:.3f}s, q={ms_q_ivf:.4f}ms, R@10={rec_ivf:.3f}, mem={mem_ivf_mb:.2f}MB"
                )

    if not filas:
        raise SystemExit("[vector_compare] No se generaron filas. Construye al menos 1k o usa --sintetico-faltantes.")

    ruta_salida = Path(args.salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        w.writeheader()
        w.writerows(filas)

    generar_resumen_md(filas, MD_RESUMEN)
    print(f"[vector_compare] Resultados guardados en:\n  - {ruta_salida}\n  - {MD_RESUMEN}")

    if args.plot:
        from bench import plots
        plots.graficar_vector()


if __name__ == "__main__":
    main()
