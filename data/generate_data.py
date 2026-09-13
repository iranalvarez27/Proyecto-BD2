"""
=============================================================================
  GENERADOR DE DATOS DE PRUEBA Y BENCHMARK (Sección 2.1.6)
  Proyecto BD2 – Minigestor Multimodal
=============================================================================

  Genera conjuntos de datos sintéticos realistas directamente en la carpeta
  data/ para las tablas:
    • estudiantes  (HeapFile + B+ Tree en 'id' + Hash Extensible en 'carrera')
    • cursos       (SequentialFile + B+ Agrupado en 'codigo')

  Permite generar:
    - 1 000 registros (1K)
    - 10 000 registros (10K)
    - 100 000 registros (100K)
    - Reset a datos de muestra iniciales (8 estudiantes, 6 cursos)

  Uso:
    python3 data/generate_data.py               (modo interactivo)
    python3 data/generate_data.py --size 1000   (o 1k, 10k, 100k)
    python3 data/generate_data.py --reset       (volver a datos iniciales)
    python3 data/generate_data.py --stats       (ver estado actual de data/)
=============================================================================
"""

import os
import sys
import time
import shutil
import random
import argparse
from typing import List, Tuple

# Asegurar importación del proyecto
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.types import Schema, Column, DataType, RID
from common.record import Record
from storage.heap_file import HeapFile
from storage.sequential_file import (
    SequentialFile,
    SequentialEntry,
    MAIN_FILE,
    AUX_FILE,
)
from index.bplus_tree import BPlusTree
from index.extendible_hash import ExtendibleHash
from index.clustered_bplus_tree import ClusteredBPlusTree

DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# ─── ESQUEMAS OFICIALES ───────────────────────────────────────────────────────
SCHEMA_ESTUDIANTES = Schema(
    table_name="estudiantes",
    columns=[
        Column(name="id", type=DataType.INT, size=4, is_pk=True),
        Column(name="nombre", type=DataType.VARCHAR, size=40, is_pk=False),
        Column(name="carrera", type=DataType.VARCHAR, size=30, is_pk=False),
        Column(name="promedio", type=DataType.FLOAT, size=4, is_pk=False),
    ],
)

SCHEMA_CURSOS = Schema(
    table_name="cursos",
    columns=[
        Column(name="codigo", type=DataType.INT, size=4, is_pk=True),
        Column(name="titulo", type=DataType.VARCHAR, size=50, is_pk=False),
        Column(name="creditos", type=DataType.SMALLINT, size=2, is_pk=False),
        Column(name="departamento", type=DataType.VARCHAR, size=20, is_pk=False),
    ],
)

# ─── DATOS REALISTAS ─────────────────────────────────────────────────────────
NOMBRES = [
    "Ana", "Mateo", "Lucia", "Diego", "Sofia", "Carlos", "Valeria", "Jorge",
    "Camila", "Sebastian", "Maria", "Alejandro", "Valentina", "Gabriel", "Isabella",
    "Daniel", "Mariana", "Nicolas", "Paula", "Andres", "Elena", "Lucas",
    "Gabriela", "Martin", "Renata", "Felipe", "Daniela", "Joaquin", "Adriana", "Alonso"
]

APELLIDOS = [
    "Torres", "Silva", "Morales", "Castro", "Vargas", "Vega", "Rivas", "Herrera",
    "Fernandez", "Reyes", "Gomez", "Mendoza", "Perez", "Guerrero", "Navarro",
    "Salazar", "Rios", "Campos", "Flores", "Rojas", "Espinoza", "Cordova",
    "Paredes", "Chavez", "Quispe", "Huaman", "Soto", "Alvarez", "Castillo", "Villanueva"
]

CARRERAS = [
    "Ciencia de la Computacion",
    "Ciencia de Datos",
    "Ingenieria de Software",
    "Bioingenieria",
    "Ingenieria Mecatronica",
    "Ingenieria Industrial",
    "Ingenieria Electronica",
    "Administracion y Negocios",
]

AREAS_CURSOS = [
    ("Base de Datos", "Computacion", [3, 4]),
    ("Estructuras de Datos", "Computacion", [4]),
    ("Algoritmos Avanzados", "Computacion", [4]),
    ("Sistemas Operativos", "Computacion", [4]),
    ("Redes de Computadoras", "Computacion", [3, 4]),
    ("Inteligencia Artificial", "Computacion", [3, 4]),
    ("Compiladores", "Computacion", [4]),
    ("Ingenieria de Software", "Computacion", [3, 4]),
    ("Seguridad Informatica", "Computacion", [3]),
    ("Cloud Computing", "Computacion", [3]),
    ("Calculo", "Matematica", [4, 5]),
    ("Algebra Lineal", "Matematica", [4]),
    ("Estadistica Aplicada", "Matematica", [3, 4]),
    ("Matematica Discreta", "Matematica", [4]),
    ("Fisica General", "Ciencias", [4]),
    ("Quimica", "Ciencias", [3]),
    ("Circuitos Electronicos", "Electronica", [3, 4]),
    ("Sistemas Embebidos", "Electronica", [3, 4]),
    ("Etica y Sociedad", "Humanidades", [2]),
    ("Comunicacion Efectiva", "Humanidades", [2]),
    ("Liderazgo e Innovacion", "Humanidades", [2]),
    ("Gestion de Proyectos", "Ingenieria", [3]),
    ("Termodinamica", "Ingenieria", [4]),
    ("Mecanica de Fluidos", "Ingenieria", [4]),
    ("Automatizacion Industrial", "Ingenieria", [3, 4]),
]


def _format_bytes(n_bytes: int) -> str:
    if n_bytes < 1024:
        return f"{n_bytes} B"
    elif n_bytes < 1024 * 1024:
        return f"{n_bytes / 1024:.2f} KB"
    else:
        return f"{n_bytes / (1024 * 1024):.2f} MB"


def _clean_data_files():
    """Elimina los archivos .bin e .idx en data/ para empezar limpio."""
    os.makedirs(DATA_DIR, exist_ok=True)
    for fname in [
        "estudiantes.bin",
        "estudiantes_id_bplus.idx",
        "estudiantes_carrera_hash.idx",
        "cursos.bin",
        "cursos_aux.bin",
        "cursos_clustered.idx",
    ]:
        fpath = os.path.join(DATA_DIR, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass


def generate_estudiantes_data(n: int) -> List[Tuple[int, str, str, float]]:
    """Genera N tuplas de estudiantes con IDs del 1 al N."""
    random.seed(42 + n)
    data = []
    for i in range(1, n + 1):
        nombre = f"{random.choice(NOMBRES)} {random.choice(APELLIDOS)}"
        carrera = random.choice(CARRERAS)
        promedio = round(random.uniform(11.0, 19.8), 2)
        data.append((i, nombre, carrera, promedio))
    return data


def generate_cursos_data(n: int) -> List[Tuple[int, str, int, str]]:
    """Genera N tuplas de cursos con códigos ordenados del 101 en adelante."""
    random.seed(1337 + n)
    data = []
    n_areas = len(AREAS_CURSOS)
    for i in range(n):
        codigo = 101 + i
        base_name, depto, cred_options = AREAS_CURSOS[i % n_areas]
        nivel = (i // n_areas) + 1
        titulo = f"{base_name} {nivel}" if nivel > 1 else base_name
        titulo = titulo[:50]
        creditos = random.choice(cred_options)
        data.append((codigo, titulo, creditos, depto))
    return data


def build_estudiantes(n: int):
    """Puebla estudiantes (HeapFile) e índices B+ Tree y Extendible Hash."""
    print(f"\n[1/2] Generando tabla 'estudiantes' (HeapFile + B+ Tree + Hash) con {n:,} registros...")
    data = generate_estudiantes_data(n)

    heap_path = os.path.join(DATA_DIR, "estudiantes.bin")
    bplus_path = os.path.join(DATA_DIR, "estudiantes_id_bplus.idx")
    hash_path = os.path.join(DATA_DIR, "estudiantes_carrera_hash.idx")

    heap = HeapFile(heap_path)
    bplus = BPlusTree(bplus_path, DataType.INT)
    eh = ExtendibleHash(hash_path)

    # 1. Inserción en HeapFile
    t0 = time.perf_counter()
    rids = []
    for row in data:
        rec = Record(list(row))
        rid = heap.insert(rec, SCHEMA_ESTUDIANTES)
        rids.append((row[0], row[2], rid))  # (id, carrera, rid)
    t_heap = time.perf_counter() - t0

    # 2. Construcción de B+ Tree en 'id'
    t0 = time.perf_counter()
    for student_id, _, rid in rids:
        bplus.insert(student_id, rid)
    t_bplus = time.perf_counter() - t0

    # 3. Construcción de Extendible Hash en 'carrera'
    t0 = time.perf_counter()
    for _, carrera, rid in rids:
        eh.insert(carrera, rid)
    t_hash = time.perf_counter() - t0

    sz_heap = os.path.getsize(heap_path) if os.path.exists(heap_path) else 0
    sz_bplus = os.path.getsize(bplus_path) if os.path.exists(bplus_path) else 0
    sz_hash = os.path.getsize(hash_path) if os.path.exists(hash_path) else 0

    print(f"  ✓ HeapFile:         {t_heap * 1000:>8.2f} ms  |  Disco: {_format_bytes(sz_heap)}")
    print(f"  ✓ B+ Tree (id):     {t_bplus * 1000:>8.2f} ms  |  Disco: {_format_bytes(sz_bplus)}")
    print(f"  ✓ Hash (carrera):   {t_hash * 1000:>8.2f} ms  |  Disco: {_format_bytes(sz_hash)}")

    return {
        "heap_time": t_heap,
        "bplus_time": t_bplus,
        "hash_time": t_hash,
        "heap_size": sz_heap,
        "bplus_size": sz_bplus,
        "hash_size": sz_hash,
    }


def build_cursos(n: int):
    """Puebla cursos (SequentialFile) y construye el B+ Clustered Tree."""
    print(f"\n[2/2] Generando tabla 'cursos' (SequentialFile + Clustered B+) con {n:,} registros...")
    data = generate_cursos_data(n)

    data_path = os.path.join(DATA_DIR, "cursos.bin")
    aux_path = os.path.join(DATA_DIR, "cursos_aux.bin")
    clustered_path = os.path.join(DATA_DIR, "cursos_clustered.idx")

    seq = SequentialFile(data_path, aux_path, SCHEMA_CURSOS, "codigo")

    # Para SequentialFile, poblar de forma estructurada en MAIN (igual que reorganize())
    # garantiza orden físico perfecto O(N) sin degradar por inserciones individuales
    t0 = time.perf_counter()
    records = [Record(list(row)) for row in data]
    pointers = []
    for rec in records:
        entry = SequentialEntry(record=rec, next_pointer=None, deleted=False)
        p = seq._append_entry(MAIN_FILE, entry)
        pointers.append(p)

    # Enlazar punteros secuenciales contiguos
    for i in range(len(pointers) - 1):
        entry = seq._read_entry(pointers[i])
        entry.next_pointer = pointers[i + 1]
        seq._write_entry(pointers[i], entry)

    t_seq = time.perf_counter() - t0

    # Construcción de Clustered B+ Tree sobre SequentialFile
    t0 = time.perf_counter()
    clustered = ClusteredBPlusTree(seq, clustered_path)
    t_clustered = time.perf_counter() - t0

    sz_data = os.path.getsize(data_path) if os.path.exists(data_path) else 0
    sz_aux = os.path.getsize(aux_path) if os.path.exists(aux_path) else 0
    sz_cl = os.path.getsize(clustered_path) if os.path.exists(clustered_path) else 0

    print(f"  ✓ SequentialFile:   {t_seq * 1000:>8.2f} ms  |  Disco (MAIN+AUX): {_format_bytes(sz_data + sz_aux)}")
    print(f"  ✓ B+ Clustered:     {t_clustered * 1000:>8.2f} ms  |  Disco: {_format_bytes(sz_cl)}")

    return {
        "seq_time": t_seq,
        "clustered_time": t_clustered,
        "seq_size": sz_data + sz_aux,
        "clustered_size": sz_cl,
    }


def reset_to_initial():
    """Restaura los datos de muestra iniciales (8 estudiantes, 6 cursos)."""
    print("\nRestaurando datos iniciales de prueba...")
    _clean_data_files()

    # Estudiantes iniciales
    sample_estudiantes = [
        (1, "Ana Torres", "Ciencia de la Computacion", 18.5),
        (2, "Mateo Silva", "Ingenieria de Software", 16.2),
        (3, "Lucia Morales", "Ciencia de Datos", 17.8),
        (4, "Diego Castro", "Ciencia de la Computacion", 15.4),
        (5, "Sofia Vargas", "Bioingenieria", 19.1),
        (6, "Carlos Vega", "Ciencia de la Computacion", 14.9),
        (7, "Valeria Rivas", "Ingenieria Mecatronica", 16.7),
        (8, "Jorge Herrera", "Ciencia de Datos", 17.0),
    ]
    heap = HeapFile(os.path.join(DATA_DIR, "estudiantes.bin"))
    bplus = BPlusTree(os.path.join(DATA_DIR, "estudiantes_id_bplus.idx"), DataType.INT)
    eh = ExtendibleHash(os.path.join(DATA_DIR, "estudiantes_carrera_hash.idx"))

    for row in sample_estudiantes:
        rec = Record(list(row))
        rid = heap.insert(rec, SCHEMA_ESTUDIANTES)
        bplus.insert(row[0], rid)
        eh.insert(row[2], rid)

    # Cursos iniciales
    sample_cursos = [
        (101, "Base de Datos 1", 4, "Computacion"),
        (102, "Algoritmos y Estructuras", 4, "Computacion"),
        (201, "Base de Datos 2", 4, "Computacion"),
        (205, "Inteligencia Artificial", 3, "Computacion"),
        (310, "Sistemas Operativos", 4, "Computacion"),
        (405, "Redes y Comunicaciones", 3, "Electronica"),
    ]
    seq = SequentialFile(
        os.path.join(DATA_DIR, "cursos.bin"),
        os.path.join(DATA_DIR, "cursos_aux.bin"),
        SCHEMA_CURSOS,
        "codigo",
    )
    for row in sample_cursos:
        seq.insert(Record(list(row)))

    ClusteredBPlusTree(seq, os.path.join(DATA_DIR, "cursos_clustered.idx"))
    print("✓ Datos iniciales restaurados con éxito (8 estudiantes, 6 cursos).")


def print_stats():
    """Muestra el estado actual de los archivos en data/."""
    print("\n" + "=" * 65)
    print("  ESTADO ACTUAL DE LA CARPETA data/")
    print("=" * 65)
    files = [
        ("estudiantes.bin", "HeapFile (datos)"),
        ("estudiantes_id_bplus.idx", "B+ Tree no agrupado en 'id'"),
        ("estudiantes_carrera_hash.idx", "Hash Dinámico en 'carrera'"),
        ("cursos.bin", "SequentialFile MAIN (datos)"),
        ("cursos_aux.bin", "SequentialFile AUX (overflow)"),
        ("cursos_clustered.idx", "B+ Tree agrupado en 'codigo'"),
    ]
    total_size = 0
    for fname, desc in files:
        fpath = os.path.join(DATA_DIR, fname)
        if os.path.exists(fpath):
            sz = os.path.getsize(fpath)
            total_size += sz
            print(f"  • {fname:<30} {_format_bytes(sz):>10}  ({desc})")
        else:
            print(f"  • {fname:<30}     NO EXISTE  ({desc})")

    print("-" * 65)
    print(f"  Espacio total en disco: {_format_bytes(total_size)}")
    print("=" * 65)


def print_cheat_sheet(n: int):
    """Muestra consultas SQL recomendadas para ejecutar en el Frontend."""
    print("\n" + "=" * 75)
    print(f"  GUÍA DE CONSULTAS PARA EL FRONTEND (Con dataset de {n:,} registros)")
    print("=" * 75)
    print("""
1. Búsqueda por Igualdad Exacta:
   • B+ Tree (no agrupado en Heap):
       SELECT * FROM estudiantes WHERE id = 500;
   • Hash Dinámico (en Heap):
       SELECT * FROM estudiantes WHERE carrera = 'Ciencia de Datos';
   • B+ Agrupado (en Sequential):
       SELECT * FROM cursos WHERE codigo = 250;

2. Búsqueda por Rango:
   • B+ Tree no agrupado:
       SELECT * FROM estudiantes WHERE id BETWEEN 100 AND 300;
   • B+ Tree agrupado:
       SELECT * FROM cursos WHERE codigo BETWEEN 100 AND 300;

3. Recorrido Ordenado (ORDER BY):
   • B+ Tree:
       SELECT * FROM estudiantes ORDER BY id ASC;
   • Sequential / B+ Agrupado:
       SELECT * FROM cursos ORDER BY codigo ASC;

4. Consultas con Agrupación:
       SELECT carrera, COUNT(id), AVG(promedio) FROM estudiantes GROUP BY carrera;
    """)
    print("💡 En el Panel de Plan de Ejecución podrás ver el árbol con el índice")
    print("   utilizado, y en el Panel de Resultados verás el tiempo exacto en ms.")
    print("=" * 75)


def main():
    parser = argparse.ArgumentParser(description="Generador de datos de benchmark para BD2")
    parser.add_argument("--size", type=str, help="Cantidad de registros: 1000, 10000, 100000 (o 1k, 10k, 100k)")
    parser.add_argument("--reset", action="store_true", help="Restaurar a datos iniciales de prueba")
    parser.add_argument("--stats", action="store_true", help="Ver estado de archivos en data/")

    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    if args.reset:
        reset_to_initial()
        return

    n = None
    if args.size:
        size_str = args.size.strip().lower()
        mapping = {
            "1000": 1000, "1k": 1000,
            "10000": 10000, "10k": 10000,
            "100000": 100000, "100k": 100000,
        }
        if size_str in mapping:
            n = mapping[size_str]
        else:
            try:
                n = int(size_str)
            except ValueError:
                print(f"Error: tamaño '{args.size}' no reconocido. Usa 1k, 10k o 100k.")
                sys.exit(1)

    if n is None:
        # Menú interactivo
        print("\n" + "=" * 65)
        print("  GENERADOR DE DATOS Y BENCHMARK – SECCIÓN 2.1.6")
        print("=" * 65)
        print("Selecciona el tamaño de datos a generar en data/:")
        print("  [1]   1 000 registros (1K)    - Generación ultrarrápida (~1 s)")
        print("  [2]  10 000 registros (10K)   - Recomendado para pruebas (~3 s)")
        print("  [3] 100 000 registros (100K)  - Benchmark completo (~25 s)")
        print("  [4] Reset a datos iniciales   (8 estudiantes, 6 cursos)")
        print("  [5] Ver estadísticas actuales de data/")
        print("  [q] Salir")
        print("=" * 65)

        opc = input("Opción [1-5]: ").strip().lower()
        if opc == "1":
            n = 1000
        elif opc == "2":
            n = 10000
        elif opc == "3":
            n = 100000
        elif opc == "4":
            reset_to_initial()
            return
        elif opc == "5":
            print_stats()
            return
        elif opc in ("q", "quit", "exit"):
            return
        else:
            print("Opción inválida.")
            return

    print("\n" + "=" * 65)
    print(f"  INICIANDO GENERACIÓN DE {n:,} REGISTROS")
    print("=" * 65)

    _clean_data_files()
    t_total_0 = time.perf_counter()

    res_est = build_estudiantes(n)
    res_cur = build_cursos(n)

    t_total = time.perf_counter() - t_total_0

    print("\n" + "=" * 65)
    print(f"  RESUMEN DE GENERACIÓN ({n:,} REGISTROS)")
    print("=" * 65)
    print(f"  Tiempo total de generación: {t_total:.2f} s")
    print(f"  • HeapFile + B+ + Hash:     {res_est['heap_time'] + res_est['bplus_time'] + res_est['hash_time']:.2f} s")
    print(f"  • SequentialFile + B+ Clust:{res_cur['seq_time'] + res_cur['clustered_time']:.2f} s")
    print_stats()
    print_cheat_sheet(n)


if __name__ == "__main__":
    main()
