import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from index.vector.exacto import knn_exacto_lote

from . import cache, codebook, config
from .mfcc import cargar_audio, extraer_mfcc
from .sift import extraer_sift


VALORES_K = (128, 256, 512, 1024)


def _etiqueta(oid, etiquetas):
    if not etiquetas:
        return None
    candidatos = [oid]
    if isinstance(oid, tuple):
        candidatos.extend([oid[0], str(oid[0])])
    candidatos.append(str(oid))
    for c in candidatos:
        if c in etiquetas:
            return etiquetas[c]
    return None


def _misma_pista(a, b) -> bool:
    if isinstance(a, tuple) and isinstance(b, tuple):
        return a[0] == b[0]
    return a == b


def _descriptores_de_archivo(tipo, ruta, meta):
    if tipo == "imagen":
        return extraer_sift(ruta, int(meta["max_lado"]), int(meta["nfeatures"]))
    y = cargar_audio(ruta, int(meta["sr"]))
    return extraer_mfcc(
        y, sr=int(meta["sr"]), n_fft=int(meta["n_fft"]),
        hop=int(meta["hop"]), n_mfcc=int(meta["n_mfcc"]),
    )


def _medir_transformacion(tipo, muestras, codebook_, idf_vec, estandarizacion,
                          limite=20) -> float:
    from .bovw import tfidf_denso

    if not muestras:
        return float("nan")
    inicio = time.perf_counter()
    for desc in muestras[:limite]:
        if tipo == "audio":
            desc = codebook.aplicar_estandarizacion(desc, estandarizacion)
        tfidf_denso(codebook.histograma(desc, codebook_), idf_vec)
    return 1000 * (time.perf_counter() - inicio) / min(len(muestras), limite)


def _medir_extractfeatures(tipo, objetos, meta, codebook_, idf_vec,
                           estandarizacion, limite=10) -> float:
    from .bovw import tfidf_denso

    if not objetos:
        return float("nan")
    elegidos = objetos[:limite]
    inicio = time.perf_counter()
    for _, ruta in elegidos:
        desc = _descriptores_de_archivo(tipo, ruta, meta)
        if tipo == "audio":
            desc = codebook.aplicar_estandarizacion(desc, estandarizacion)
        tfidf_denso(codebook.histograma(desc, codebook_), idf_vec)
    return 1000 * (time.perf_counter() - inicio) / len(elegidos)


def _evaluar(vectores, ids, etiquetas, k: int, excluir_misma_pista: bool):
    n = len(ids)
    if n == 0:
        return {
            "precision@10": None,
            "auto_consulta": 0.0,
            "distancia_media": None,
            "por_etiqueta": {},
        }

    vectores = np.asarray(vectores, dtype=np.float64)
    normas2 = np.einsum("ij,ij->i", vectores, vectores)

    # Se piden vecinos de mas para poder descartar la propia consulta y, en
    # audio, los demas segmentos de la misma pista sin quedarnos sin ranking.
    margen = 0
    if excluir_misma_pista:
        conteo = defaultdict(int)
        for oid in ids:
            conteo[oid[0] if isinstance(oid, tuple) else oid] += 1
        margen = max(conteo.values()) - 1

    pedir = min(n, max(2, k + 1 + margen))
    posiciones, distancias_knn = knn_exacto_lote(vectores, vectores, pedir, "euclidean")

    precisiones = []
    por_etiqueta = defaultdict(list)
    distancias_medias = []

    for i in range(n):
        # La propia consulta se excluye por indice (no por distancia: puede
        # haber empates en 0 con vectores repetidos).
        ranking = [
            (int(j), float(d))
            for j, d in zip(posiciones[i], distancias_knn[i])
            if int(j) != i
        ]
        if excluir_misma_pista:
            ranking = [
                (j, d) for j, d in ranking if not _misma_pista(ids[i], ids[j])
            ]
        vecinos = [j for j, _ in ranking[:k]]

        # Distancia al vecino mas cercano que si es comparable.
        if ranking:
            distancias_medias.append(ranking[0][1])

        etiqueta = _etiqueta(ids[i], etiquetas)
        if etiqueta is None or not vecinos:
            continue
        aciertos = sum(1 for j in vecinos if _etiqueta(ids[j], etiquetas) == etiqueta)
        precision = aciertos / len(vecinos)
        precisiones.append(precision)
        por_etiqueta[etiqueta].append(precision)

    # Auto-consulta: el vecino mas cercano debe estar a distancia practicamente
    # nula (el propio vector o un duplicado exacto). euclidiana se calcula como
    # ||q||² + ||x||² - 2q·x y en float32 deja un piso de error del orden de
    # 1e-3 de la norma, por eso el umbral se escala con cada vector. Comparar
    # indices fallaria con histogramas repetidos.
    auto = sum(
        1 for i in range(n)
        if len(distancias_knn[i])
        and float(distancias_knn[i][0]) <= 1e-2 * float(np.sqrt(normas2[i]))
    ) / n

    return {
        "precision@10": float(np.mean(precisiones)) if precisiones else None,
        "auto_consulta": float(auto),
        "distancia_media": float(np.mean(distancias_medias)) if distancias_medias else None,
        "por_etiqueta": {
            str(e): float(np.mean(v)) for e, v in sorted(por_etiqueta.items())
        },
    }


def barrido_k(tipo: str, N: int = 1_000, valores_k=VALORES_K, *,
              base=None, directorio=None, cache_dir=None,
              etiquetas: dict | None = None,
              k: int = 10,
              muestra: int = config.MUESTRA_KMEANS,
              semilla: int = config.SEMILLA,
              excluir_misma_pista: bool | None = None,
              limite_tiempo: int = 20) -> list[dict]:
    tipo = config.validar_tipo(tipo)
    modelo_dir = Path(directorio) if directorio is not None else config.directorio_modelo(tipo, base)
    cache_dir = Path(cache_dir) if cache_dir is not None else modelo_dir / "cache"

    resumen = cache.resumen_cache(tipo, directorio=cache_dir)
    ids_cache = cache.ids_objetos(tipo, directorio=cache_dir)
    if not ids_cache:
        raise ValueError(f"no hay cache en {cache_dir}; construyala antes del barrido")
    if excluir_misma_pista is None:
        excluir_misma_pista = tipo == "audio"

    if len(ids_cache) < N:
        raise ValueError(f"la cache tiene {len(ids_cache)} objetos y se pidieron {N}")
    ids_cache = ids_cache[:N]

    pares = cache.leer_descriptores(tipo, ids_cache, directorio=cache_dir)
    descriptores_cache = [desc for _, desc in pares]

    muestra_desc = codebook.muestrear_estratificado(
        pares, ids_cache, total=muestra, semilla=semilla,
    )

    estandarizacion = None
    if tipo == "audio":
        estandarizacion = codebook.calcular_estandarizacion(muestra_desc)
        muestra_desc = codebook.aplicar_estandarizacion(muestra_desc, estandarizacion)

    objetos = cache.rutas(tipo, directorio=cache_dir) or None
    meta = {**config.parametros(tipo), **resumen.get("params", {})}

    from .bovw import calcular_idf, tfidf_denso
    from .kmeans import kmeans as _kmeans

    filas = []
    for K in valores_k:
        K = int(K)
        if K > len(muestra_desc):
            filas.append({"K": K, "error": f"K > muestra ({len(muestra_desc)})"})
            continue

        inicio = time.perf_counter()
        cb = _kmeans(muestra_desc, K, semilla=semilla)

        C = np.empty((N, K), dtype=np.int64)
        for i, desc in enumerate(descriptores_cache):
            if tipo == "audio":
                desc = codebook.aplicar_estandarizacion(desc, estandarizacion)
            C[i] = codebook.histograma(desc, cb)

        idf_vec = calcular_idf(C)
        vectores = np.empty((N, K), dtype=np.float32)
        for i in range(N):
            vectores[i] = tfidf_denso(C[i], idf_vec)
        segundos_offline = time.perf_counter() - inicio

        evaluacion = _evaluar(vectores, ids_cache, etiquetas, k, excluir_misma_pista)
        fila = {
            "tipo": tipo,
            "N": N,
            "K": K,
            "muestra": int(len(muestra_desc)),
            "segundos_offline": round(segundos_offline, 3),
            "ms_transformacion": round(
                _medir_transformacion(
                    tipo, descriptores_cache, cb, idf_vec, estandarizacion,
                    limite_tiempo,
                ), 3,
            ),
            "ms_extractfeatures": round(
                _medir_extractfeatures(
                    tipo, objetos, meta, cb, idf_vec, estandarizacion,
                    max(1, limite_tiempo // 2),
                ), 3,
            ) if objetos else None,
            **evaluacion,
        }
        filas.append(fila)
        print(
            f"[{tipo}] K={K}: precision@10={fila['precision@10']} "
            f"auto={fila['auto_consulta']:.3f} offline={fila['segundos_offline']}s",
            flush=True,
        )

    return filas


def mejor_k(filas: list[dict]) -> dict:
    validas = [f for f in filas if not f.get("error") and f.get("K")]
    if not validas:
        raise ValueError("el barrido no produjo ninguna fila valida")

    def clave(fila):
        precision = fila.get("precision@10")
        if precision is None:
            precision = -1.0
        return (
            float(precision),
            float(fila.get("auto_consulta") or 0.0),
            -int(fila["K"]),
        )

    return dict(max(validas, key=clave))


def guardar_mejor_k(filas: list[dict], ruta) -> dict:
    ruta = Path(ruta)
    elegido = mejor_k(filas)
    datos = {}
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError):
            datos = {}
    tipo = elegido.get("tipo")
    if tipo:
        datos[tipo] = elegido
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, default=str)
    return elegido


def guardar_tabla(filas: list[dict], ruta_csv, ruta_md=None, ruta_json=None) -> None:
    ruta_csv = Path(ruta_csv)
    ruta_csv.parent.mkdir(parents=True, exist_ok=True)
    campos = ["tipo", "N", "K", "muestra", "precision@10", "auto_consulta",
              "distancia_media", "segundos_offline", "ms_transformacion",
              "ms_extractfeatures", "error"]
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow(fila)

    if ruta_md:
        lineas = [
            "| " + " | ".join(campos) + " |",
            "|" + "|".join(["---"] * len(campos)) + "|",
        ]
        for fila in filas:
            lineas.append("| " + " | ".join(
                "" if fila.get(c) is None else str(fila.get(c, "")) for c in campos
            ) + " |")
        Path(ruta_md).write_text("\n".join(lineas) + "\n", encoding="utf-8")

    if ruta_json:
        # Conserva tambien el detalle por etiqueta (categoria/genero).
        Path(ruta_json).write_text(
            json.dumps(filas, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def graficar(filas: list[dict], ruta_png) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    validas = [f for f in filas if f.get("precision@10") is not None]
    if not validas:
        return False

    ks = [f["K"] for f in validas]
    precision = [f["precision@10"] for f in validas]
    fig, eje = plt.subplots(figsize=(7, 4))
    eje.plot(ks, precision, marker="o")
    eje.set_xscale("log", base=2)
    eje.set_xlabel("K (palabras del codebook)")
    eje.set_ylabel("Precision@10")
    eje.set_title("Eleccion de K")
    eje.grid(True, alpha=0.3)
    fig.tight_layout()
    Path(ruta_png).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Barrido de K (F10)")
    parser.add_argument("--tipo", choices=("imagen", "audio"), required=True)
    parser.add_argument("--n", type=int, default=1_000)
    parser.add_argument("--ks", default=",".join(map(str, VALORES_K)))
    parser.add_argument("--base", default=None)
    parser.add_argument("--etiquetas", default=None,
                        help="JSON {id: etiqueta} para Precision@10")
    parser.add_argument("--salida", default=None)
    parser.add_argument("--muestra", type=int, default=config.MUESTRA_KMEANS)
    parser.add_argument("--grafica", action="store_true")
    args = parser.parse_args(argv)

    etiquetas = None
    if args.etiquetas:
        with open(args.etiquetas, "r", encoding="utf-8") as f:
            etiquetas = json.load(f)

    valores_k = tuple(int(x) for x in args.ks.split(",") if x.strip())
    filas = barrido_k(
        args.tipo, args.n, valores_k, base=args.base,
        etiquetas=etiquetas, muestra=args.muestra,
    )

    base = Path(args.base) if args.base else config.BASE
    salida = Path(args.salida) if args.salida else base / "barrido_k" / f"{args.tipo}.csv"
    guardar_tabla(
        filas, salida, salida.with_suffix(".md"), salida.with_suffix(".json"),
    )
    print(f"tabla: {salida}")

    elegido = guardar_mejor_k(filas, base / "barrido_k" / "k_elegido.json")
    print(
        f"K elegido para {args.tipo}: {elegido['K']} "
        f"(precision@10={elegido.get('precision@10')}); "
        f"guardado en {base / 'barrido_k' / 'k_elegido.json'}"
    )

    if args.grafica:
        png = salida.with_suffix(".png")
        if graficar(filas, png):
            print(f"grafica: {png}")
        else:
            print("matplotlib no esta instalado o no hay Precision@10 para graficar")


if __name__ == "__main__":
    main()
