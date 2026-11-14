"""Barra de busqueda de la tienda: BM25, embeddings MiniLM y popularidad, solos y combinados.

Sin juicios de relevancia, cada consulta apunta a una subcategoria y se mide P@10 como la
fraccion del top-10 que cae en ella. Los accesorios que Amazon cataloga dentro de la
subcategoria cuentan como aciertos, asi que el top-5 de algunas consultas se imprime aparte.
"""
import csv
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCH_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recomendacion.recomendador import Servicio
from recomendacion.repositorio import Repositorio
from text.ingesta import abrir_motor

CSV_RESULTADOS = BENCH_DIR / "results" / "tienda_busqueda.csv"
CONSULTAS = {
    "mechanical keyboard": "Keyboards", "wireless mouse": "Mice", "gaming headset": "Headsets",
    "wireless earbuds": "Earbuds", "noise cancelling headphones": "Headphones", "bluetooth speaker": "Bluetooth Speakers",
    "soundbar": "Sound Bars", "mirrorless camera": "Mirrorless", "dslr camera": "DSLR", "action camera": "Action Cameras",
    "camera lens": "Lenses", "gaming monitor 27": "Monitors", "graphics card": "Graphics Cards", "ddr4 ram": "Memory",
    "cpu processor": "Processors", "external ssd": "External SSDs", "usb flash drive": "USB Flash Drives",
    "mesh wifi": "Mesh Wi-Fi", "network switch": "Switches", "drawing tablet": "Graphics Tablets",
}
CONFIGURACIONES = {
    "bm25": {"bm25": 1},
    "bm25 + popularidad": {"bm25": .8, "popularidad": .2},
    "semantico (MiniLM)": {"semantico": 1},
    "bm25 + semantico + popularidad": {"bm25": .4, "semantico": .4, "popularidad": .2},
}
MOSTRAR = ("mechanical keyboard", "graphics card")


def main():
    conexion = abrir_motor(str(PROJECT_ROOT / "data"))
    try:
        servicio = Servicio(conexion)
        servicio.verificar()
        repo = Repositorio(conexion)
        filas = repo.ejecutar("SELECT id, nombre, subcategoria FROM ecommerce_productos")
        productos = {f["id"]: f for f in filas}
        resultados = []
        for nombre, pesos in CONFIGURACIONES.items():
            precisiones = []
            for consulta, subcategoria in CONSULTAS.items():
                top = [i for i, _ in servicio.buscar(Repositorio(conexion), consulta, pesos)[:10]]
                p10 = sum(productos[i]["subcategoria"] == subcategoria for i in top) / 10
                precisiones.append(p10)
                resultados.append([nombre, consulta, subcategoria, p10])
                if consulta in MOSTRAR:
                    print(f"  [{nombre}] {consulta}: {[productos[i]['nombre'][:30] for i in top[:5]]}")
            print(f"[tienda_busqueda] {nombre:34} P@10 medio {sum(precisiones) / len(precisiones):.3f}")
    finally:
        conexion.pool.close_all()
    CSV_RESULTADOS.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_RESULTADOS, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["configuracion", "consulta", "subcategoria", "p_at_10"])
        escritor.writerows(resultados)


if __name__ == "__main__":
    main()
