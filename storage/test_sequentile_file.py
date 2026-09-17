import os
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from common.record import Record
from common.types import Schema, Column, DataType

from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from sequential_file import (
    SequentialFile,
    MAIN_FILE,
    AUX_FILE
)

def clean_files(*open_files):
    for obj in open_files:
        if obj is not None:
            obj.close()

    for path in [
        "test_datos.dat",
        "test_aux.dat",
        "test_datos.meta.bin",
        "test_datos.dirty.bin",
    ]:
        if os.path.exists(path):
            os.remove(path)


schema = Schema(
    table_name="alumnos",
    columns=[
        Column(
            "id",
            DataType.INT,
            4,
            is_pk=True
        ),
        Column(
            "nombre",
            DataType.VARCHAR,
            30
        ),
        Column(
            "edad",
            DataType.SMALLINT,
            2
        )
    ]
)


# ==========================================================
# PRUEBA 1: ELIMINAR HEAD
# ==========================================================

clean_files()

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

seq.insert(
    Record([10, "Ana", 20])
)

seq.insert(
    Record([20, "Pedro", 21])
)

seq.insert(
    Record([30, "Maria", 22])
)

print("ANTES:")

for record in seq.scan():
    print(record)

print()
print("ELIMINANDO HEAD 10:")

print(
    seq.delete(10)
)

print()
print("DESPUES:")

for record in seq.scan():
    print(record)

assert seq.search(10) is None
assert seq.search(20) is not None
assert seq.search(30) is not None


# ==========================================================
# PRUEBA 2: ELIMINAR ÚLTIMO E INEXISTENTE
# ==========================================================

clean_files(seq)

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

seq.insert(
    Record([10, "Ana", 20])
)

seq.insert(
    Record([20, "Pedro", 21])
)

seq.insert(
    Record([30, "Maria", 22])
)

print(
    "Eliminar 30:",
    seq.delete(30)
)

for record in seq.scan():
    print(record)

print(
    "Eliminar 999:",
    seq.delete(999)
)

assert seq.search(30) is None
assert seq.delete(999) is False


# ==========================================================
# PRUEBA 3: NUEVO MÍNIMO Y NUEVO MÁXIMO
# ==========================================================

clean_files(seq)

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

seq.insert(
    Record([20, "Pedro", 21])
)

seq.insert(
    Record([30, "Maria", 22])
)

print("ANTES:")

for record in seq.scan():
    print(record)

print()
print("INSERTANDO NUEVO MINIMO 10")

seq.insert(
    Record([10, "Ana", 20])
)

print("DESPUES:")

for record in seq.scan():
    print(record)

print()
print("INSERTANDO NUEVO MAXIMO 40")

seq.insert(
    Record([40, "Luis", 23])
)

for record in seq.scan():
    print(record)

keys = [
    record.values[0]
    for record in seq.scan()
]

assert keys == [
    10,
    20,
    30,
    40
]


# ==========================================================
# PRUEBA 4: MULTIPÁGINA
# ==========================================================

print()
print("==============================")
print("PRUEBA MULTIPAGINA")
print("==============================")

clean_files(seq)

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

# Insertamos 200 registros en orden inverso.
# Esto obliga a usar AUX y varias páginas.
for i in range(200, 0, -1):
    seq.insert(
        Record([
            i,
            "X" * 30,
            20
        ])
    )

print(
    "Paginas MAIN:",
    seq.page_count(MAIN_FILE)
)

print(
    "Paginas AUX:",
    seq.page_count(AUX_FILE)
)

records = list(
    seq.scan()
)

print(
    "Cantidad de registros:",
    len(records)
)

keys = [
    record.values[0]
    for record in records
]

print(
    "Primeras claves:",
    keys[:10]
)

print(
    "Ultimas claves:",
    keys[-10:]
)

assert len(records) == 200
assert keys == list(
    range(1, 201)
)

print("ORDEN CORRECTO")


# ==========================================================
# PRUEBA 5: REORGANIZACIÓN MULTIPÁGINA
# ==========================================================

print()
print("REORGANIZANDO MULTIPAGINA...")

seq.reorganize()

print(
    "Paginas MAIN despues:",
    seq.page_count(MAIN_FILE)
)

print(
    "Paginas AUX despues:",
    seq.page_count(AUX_FILE)
)

records = list(
    seq.scan()
)

keys = [
    record.values[0]
    for record in records
]

assert len(records) == 200

assert keys == list(
    range(1, 201)
)

assert (
    seq.page_count(AUX_FILE)
    == 0
)

print(
    "REORGANIZACION MULTIPAGINA CORRECTA"
)


# ==========================================================
# PRUEBA 6: PERSISTENCIA
# ==========================================================

print()
print("==============================")
print("PRUEBA DE PERSISTENCIA")
print("==============================")

# Cerramos el objeto,
# pero NO borramos los archivos.
seq.close()

del seq

seq2 = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

records = list(
    seq2.scan()
)

keys = [
    record.values[0]
    for record in records
]

print(
    "Registros recuperados:",
    len(records)
)

print(
    "Primeras claves:",
    keys[:10]
)

print(
    "Ultimas claves:",
    keys[-10:]
)

print(
    "Paginas MAIN:",
    seq2.page_count(MAIN_FILE)
)

print(
    "Paginas AUX:",
    seq2.page_count(AUX_FILE)
)

assert len(records) == 200

assert keys == list(
    range(1, 201)
)

print(
    "PERSISTENCIA CORRECTA"
)


# ==========================================================
# PRUEBA 7: PK DUPLICADA
# ==========================================================

print()
print("==============================")
print("PRUEBA CLAVE DUPLICADA")
print("==============================")

clean_files(seq2)

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

seq.insert(
    Record([10, "Ana", 20])
)

seq.insert(
    Record([20, "Pedro", 21])
)

seq.insert(
    Record([30, "Maria", 22])
)

print(
    "Intentando insertar ID 20 nuevamente..."
)

duplicate_rejected = False

try:
    seq.insert(
        Record([
            20,
            "Otro Pedro",
            25
        ])
    )

    print(
        "DUPLICADO ACEPTADO"
    )

except ValueError as e:
    duplicate_rejected = True

    print(
        "DUPLICADO RECHAZADO"
    )

    print(e)

assert duplicate_rejected is True

print()
print("CONTENIDO:")

for record in seq.scan():
    print(record)

keys = [
    record.values[0]
    for record in seq.scan()
]

assert keys == [
    10,
    20,
    30
]


# ==========================================================
# PRUEBA 8: REINSERTAR PK ELIMINADA
# ==========================================================

print()
print("==============================")
print("PRUEBA REINSERTAR PK ELIMINADA")
print("==============================")

print(
    "Eliminando 20..."
)

print(
    seq.delete(20)
)

print(
    "Reinsertando 20..."
)

try:
    seq.insert(
        Record([
            20,
            "Pedro Nuevo",
            25
        ])
    )

    print(
        "REINSERCION CORRECTA"
    )

except ValueError as e:
    print(
        "REINSERCION FALLIDA"
    )

    print(e)

print()
print("CONTENIDO:")

for record in seq.scan():
    print(record)

record_20 = seq.search(20)

assert record_20 is not None
assert record_20.values[1] == "Pedro Nuevo"


# ==========================================================
# PRUEBA 9: NUEVO SEARCH
# ==========================================================

print()
print("==============================")
print("PRUEBA NUEVO SEARCH")
print("==============================")

clean_files(seq)

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

# Inserciones crecientes.
# Con la optimización actual,
# entran directamente a MAIN.
for i in range(1, 201):
    seq.insert(
        Record([
            i,
            "X" * 30,
            20
        ])
    )

print(
    "MAIN pages:",
    seq.page_count(MAIN_FILE)
)

print(
    "AUX pages:",
    seq.page_count(AUX_FILE)
)

print()

print(
    "BUSCAR 1:",
    seq.search(1)
)

print(
    "BUSCAR 100:",
    seq.search(100)
)

print(
    "BUSCAR 200:",
    seq.search(200)
)

print(
    "BUSCAR 999:",
    seq.search(999)
)

assert (
    seq.search(1).values[0]
    == 1
)

assert (
    seq.search(100).values[0]
    == 100
)

assert (
    seq.search(200).values[0]
    == 200
)

assert (
    seq.search(999)
    is None
)

print(
    "BUSQUEDA EN MAIN CORRECTA"
)


# ==========================================================
# PRUEBA 10: SEARCH EN AUX
# ==========================================================

print()
print(
    "ELIMINANDO 150 Y REINSERTANDOLO EN AUX..."
)

assert (
    seq.delete(150)
    is True
)

seq.insert(
    Record([
        150,
        "Nuevo",
        25
    ])
)

print(
    "BUSCAR 150:",
    seq.search(150)
)

print(
    "AUX vivos:",
    seq.aux_record_count()
)

assert (
    seq.search(150)
    is not None
)

assert (
    seq.search(150).values[0]
    == 150
)

assert (
    seq.aux_record_count()
    == 1
)

print(
    "BUSQUEDA EN AUX CORRECTA"
)


# ==========================================================
# PRUEBA 11: SEARCH DE REGISTRO ELIMINADO
# ==========================================================

print()
print(
    "ELIMINANDO 100..."
)

assert (
    seq.delete(100)
    is True
)

print(
    "BUSCAR 100:",
    seq.search(100)
)

assert (
    seq.search(100)
    is None
)

print(
    "BUSQUEDA DE ELIMINADO CORRECTA"
)

print()

print(
    "TODAS LAS PRUEBAS DE SEARCH PASARON"
)


# ==========================================================
# PRUEBA 12: OPTIMIZACIÓN MAIN / AUX
# ==========================================================

print()
print("==============================")
print("PRUEBA OPTIMIZACION MAIN/AUX")
print("==============================")

clean_files(seq)

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

# Todos son crecientes.
# Deben ir directamente a MAIN.
seq.insert(
    Record([10, "A", 20])
)

seq.insert(
    Record([20, "B", 20])
)

seq.insert(
    Record([30, "C", 20])
)

seq.insert(
    Record([40, "D", 20])
)

print(
    "MAIN pages:",
    seq.page_count(MAIN_FILE)
)

print(
    "AUX inicial:",
    seq.aux_record_count()
)

assert (
    seq.aux_record_count()
    == 0
)


# Eliminamos físicamente de forma lazy el 40.
# La clave 40 sigue existiendo físicamente en MAIN.

print()
print(
    "ELIMINANDO 40..."
)

assert (
    seq.delete(40)
    is True
)


# 35 es mayor que el último vivo (30),
# pero menor que la última clave física MAIN (40).
# Por eso debe ir a AUX.

print(
    "INSERTANDO 35..."
)

seq.insert(
    Record([35, "E", 20])
)

print(
    "AUX despues de 35:",
    seq.aux_record_count()
)

assert (
    seq.aux_record_count()
    == 1
)


# 50 sí es mayor que la última clave física MAIN (40).
# Puede agregarse directamente a MAIN.

print(
    "INSERTANDO 50..."
)

seq.insert(
    Record([50, "F", 20])
)

print(
    "AUX despues de 50:",
    seq.aux_record_count()
)

assert (
    seq.aux_record_count()
    == 1
)


print()
print(
    "SCAN FINAL:"
)

for record in seq.scan():
    print(record)

keys = [
    record.values[0]
    for record in seq.scan()
]

assert keys == [
    10,
    20,
    30,
    35,
    50
]

print()

print(
    "OPTIMIZACION MAIN/AUX CORRECTA"
)


# ==========================================================
# FIN
# ==========================================================

seq.close()

print()
print("==============================")
print("TODAS LAS PRUEBAS PASARON")
print("==============================")


print("\n==============================")
print("PRUEBA ARCHIVO LOGICAMENTE VACIO")
print("==============================")

clean_files(seq)

seq = SequentialFile(
    BufferPool(FileManager()),
    "test_datos.dat",
    "test_aux.dat",
    schema,
    "id"
)

seq.insert(Record([10, "A", 20]))
seq.insert(Record([20, "B", 20]))

assert seq.delete(10) is True
assert seq.delete(20) is True

print("Insertando 5 después de eliminar todos...")

seq.insert(
    Record([5, "C", 20])
)

print("SCAN:", list(seq.scan()))
print("SEARCH 5:", seq.search(5))

assert seq.search(5) is not None
assert seq.search(5).values[0] == 5

seq.close()