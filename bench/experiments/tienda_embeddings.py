"""Embeddings de texto (all-MiniLM-L6-v2) vs BM25 / TF-IDF en la tienda.

1. Barra de busqueda: P@10 por subcategoria de las mismas consultas de tienda_busqueda.py,
   para BM25 + popularidad, solo embeddings del nombre y la combinacion de los tres.
2. Senal de texto del recomendador: fraccion de los 10 vecinos de texto de un producto que
   comparten su subcategoria, More Like This (TF-IDF) vs embeddings de nombre + descripcion.
"""
import csv
import math
import random
import sys
from pathlib import Path

import numpy as np

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bench.experiments.tienda_busqueda import CONSULTAS
from recomendacion.catalogo import DIR_TIENDA
from recomendacion.fusion import combinar
from recomendacion.recomendador import Servicio
from recomendacion.repositorio import Repositorio, literal
from recomendacion.semantico import Codificador
from recomendacion.texto import terminos_relevantes
from text.ingesta import abrir_motor

CSV_RESULTADOS = BENCH_DIR / "results" / "tienda_embeddings.csv"
CONSULTAS = {**CONSULTAS, "keyboard": "Keyboards"}
MUESTRA_RECOMENDACION = 300


def embeddings(nombre, textos, max_tokens):
    cache = DIR_TIENDA / f"embeddings_{nombre}.npy"
    if cache.exists() and len(np.load(cache)) == len(textos):
        return np.load(cache)
    v = Codificador(max_tokens)(textos)
    np.save(cache, v)
    return v


def main():
    with open(DIR_TIENDA / "productos.csv", encoding="utf-8", newline="") as f:
        prods = list(csv.DictReader(f))
    ids = np.array([int(p["id"]) for p in prods])
    subcat = {int(p["id"]): p["subcategoria"] for p in prods}
    nombre = {int(p["id"]): p["nombre"] for p in prods}
    v_nombre = embeddings("nombre", [p["nombre"] for p in prods], 64)
    v_texto = embeddings("texto", [" ".join(p[c] for c in ("nombre", "descripcion", "caracteristicas")) for p in prods], 256)
    codificador = Codificador(64)

    conexion = abrir_motor(str(PROJECT_ROOT / "data"))
    filas = []
    try:
        servicio = Servicio(conexion)
        servicio.verificar()
        repo = Repositorio(conexion)
        compradores = {r["id"]: r["compradores"] for r in repo.ejecutar("SELECT id, compradores FROM ecommerce_compradores")}

        def semantica(consulta, n=300):
            sim = v_nombre @ codificador([consulta])[0]
            orden = np.argsort(-sim)[:n]
            return [(int(ids[i]), float(sim[i])) for i in orden]

        def bm25(consulta):
            return [(r["id"], r["score"]) for r in repo.ejecutar(
                f"SELECT id, SCORE() AS score FROM ecommerce_textos WHERE MATCH(contenido, {literal(consulta)}) USING BM25")]

        def con_popularidad(listas, pesos):
            candidatos = {i for lista in listas.values() for i, _ in lista}
            listas = {**listas, "popularidad": [(i, math.log1p(compradores.get(i, 0))) for i in candidatos]}
            return [i for i, _ in combinar(listas, pesos)]

        configuraciones = {
            "bm25 + popularidad": lambda q: con_popularidad({"bm25": bm25(q)}, {"bm25": .8, "popularidad": .2}),
            "embeddings": lambda q: [i for i, _ in semantica(q)],
            "embeddings + popularidad": lambda q: con_popularidad({"emb": semantica(q)}, {"emb": .8, "popularidad": .2}),
            "bm25 + embeddings + popularidad": lambda q: con_popularidad(
                {"bm25": bm25(q), "emb": semantica(q)}, {"bm25": .4, "emb": .4, "popularidad": .2}),
        }
        print("[tienda_embeddings] barra de busqueda")
        for nombre_conf, buscar in configuraciones.items():
            p10 = []
            for consulta, sub in CONSULTAS.items():
                top = buscar(consulta)[:10]
                p10.append(sum(subcat[i] == sub for i in top) / 10)
                filas.append(["busqueda", nombre_conf, consulta, p10[-1]])
                if consulta in ("mechanical keyboard", "keyboard"):
                    print(f"    {consulta:20} {[nombre[i][:24] for i in top[:5]]}")
            print(f"  {nombre_conf:34} P@10 medio {sum(p10) / len(p10):.3f}")

        print("[tienda_embeddings] senal de texto del recomendador")
        muestra = random.Random(42).sample(list(ids), MUESTRA_RECOMENDACION)
        indice = conexion.catalog.get_table("ecommerce_textos").indices["contenido"][0]
        posicion = {int(i): k for k, i in enumerate(ids)}
        aciertos = {"more like this (tf-idf)": [], "embeddings nombre + descripcion": []}
        for pid in muestra:
            pid = int(pid)
            contenido = repo.ejecutar(f"SELECT contenido FROM ecommerce_textos WHERE id = {pid}")[0]["contenido"]
            terminos = terminos_relevantes(indice, contenido)
            mlt = [r["id"] for r in repo.ejecutar(
                f"SELECT id, SCORE() AS s FROM ecommerce_textos WHERE MATCH(contenido, {literal(' '.join(terminos))}) "
                f"USING TF_IDF LIMIT 11") if r["id"] != pid][:10]
            sim = v_texto @ v_texto[posicion[pid]]
            emb = [int(ids[i]) for i in np.argsort(-sim)[:11] if int(ids[i]) != pid][:10]
            for clave, vecinos in (("more like this (tf-idf)", mlt), ("embeddings nombre + descripcion", emb)):
                aciertos[clave].append(sum(subcat[i] == subcat[pid] for i in vecinos) / max(len(vecinos), 1))
        for clave, valores in aciertos.items():
            media = sum(valores) / len(valores)
            filas.append(["recomendacion", clave, "", round(media, 4)])
            print(f"  {clave:34} misma subcategoria@10 {media:.3f}")
    finally:
        conexion.pool.close_all()
    with open(CSV_RESULTADOS, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["tarea", "configuracion", "consulta", "valor"])
        escritor.writerows(filas)


if __name__ == "__main__":
    main()
