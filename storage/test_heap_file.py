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

from heap_file import HeapFile
from common.record import Record
from common.types import Schema, Column, DataType

schema = Schema(
    table_name="alumnos",
    columns=[
        Column("id", DataType.INT, 4, is_pk=True),
        Column("nombre", DataType.VARCHAR, 30),
        Column("edad", DataType.SMALLINT, 2)
    ]
)

print("\n==============================")
print("PRUEBA REUTILIZACION DE ESPACIO")
print("==============================")

if os.path.exists("test_heap.dat"):
    os.remove("test_heap.dat")

heap = HeapFile(
    "test_heap.dat"
)

# Insertamos registros
rid1 = heap.insert(
    Record([1, "Ana", 20]),
    schema
)

rid2 = heap.insert(
    Record([2, "Pedro", 21]),
    schema
)

rid3 = heap.insert(
    Record([3, "Maria", 22]),
    schema
)

print("RID 1:", rid1)
print("RID 2:", rid2)
print("RID 3:", rid3)

# Eliminamos el segundo registro
heap.delete(rid2)

print()
print(
    "READ eliminado:",
    heap.read(rid2, schema)
)

assert heap.read(rid2, schema) is None


# Insertamos otro registro.
# El Heap debería intentar reutilizar el espacio disponible.
rid4 = heap.insert(
    Record([4, "Luis", 23]),
    schema
)

print()
print(
    "RID nuevo:",
    rid4
)

print(
    "Registro nuevo:",
    heap.read(rid4, schema)
)

assert heap.read(rid4, schema) is not None
assert heap.read(rid4, schema).values[0] == 4


print()
print("SCAN:")

records = list(
    heap.scan(schema)
)

for record in records:
    print(record)

keys = [
    record.values[0]
    for record in records
]

assert 1 in keys
assert 2 not in keys
assert 3 in keys
assert 4 in keys

print()
print("REUTILIZACION DE ESPACIO CORRECTA")

heap.close()

if os.path.exists("test_heap.dat"):
    os.remove("test_heap.dat")

print("\n==============================")
print("PRUEBA REUSABLE CON TAMAÑOS VARIABLES")
print("==============================")

if os.path.exists("test_heap.dat"):
    os.remove("test_heap.dat")


schema_variable = Schema(
    table_name="datos",
    columns=[
        Column(
            "id",
            DataType.INT,
            4,
            is_pk=True
        ),
        Column(
            "texto",
            DataType.VARCHAR,
            4080
        )
    ]
)


heap = HeapFile(
    "test_heap.dat"
)


# --------------------------------------------------
# 1. Llenamos varias páginas
# --------------------------------------------------

rids = []

for i in range(12):
    rid = heap.insert(
        Record([
            i,
            "X" * 900
        ]),
        schema_variable
    )

    rids.append(rid)


print(
    "Paginas iniciales:",
    heap.page_count()
)


# --------------------------------------------------
# 2. Liberamos espacio en la página 0
# --------------------------------------------------

rid_eliminado = rids[0]

heap.delete(
    rid_eliminado
)

print(
    "RID eliminado:",
    rid_eliminado
)


# --------------------------------------------------
# 3. Intentamos insertar algo MUY grande
#
# No cabe en el hueco de la página 0.
# Esto es importante para probar _reusable.
# --------------------------------------------------

rid_grande = heap.insert(
    Record([
        100,
        "G" * 4078
    ]),
    schema_variable
)

print(
    "RID grande:",
    rid_grande
)

print(
    "Paginas despues del grande:",
    heap.page_count()
)


# --------------------------------------------------
# 4. Ahora insertamos algo muy pequeño
#
# Este SÍ debería poder aprovechar
# el hueco que quedó en página 0.
# --------------------------------------------------

rid_pequeno = heap.insert(
    Record([
        200,
        "hola"
    ]),
    schema_variable
)

print(
    "RID pequeño:",
    rid_pequeno
)

print(
    "Paginas finales:",
    heap.page_count()
)


print()
print(
    "Pagina con hueco:",
    rid_eliminado.page_id
)

print(
    "Pagina usada por pequeño:",
    rid_pequeno.page_id
)


assert heap.read(
    rid_pequeno,
    schema_variable
) is not None


# Queremos que vuelva a aprovechar
# la página que tenía espacio disponible.
assert (
    rid_pequeno.page_id
    == rid_eliminado.page_id
)


print()
print(
    "REUSABLE CON TAMAÑOS VARIABLES CORRECTO"
)


heap.close()

if os.path.exists("test_heap.dat"):
    os.remove("test_heap.dat")


    print("\n==============================")
print("PRUEBA REUTILIZACION DESPUES DE REABRIR")
print("==============================")

if os.path.exists("test_heap.dat"):
    os.remove("test_heap.dat")


schema_reopen = Schema(
    table_name="datos",
    columns=[
        Column("id", DataType.INT, 4, is_pk=True),
        Column("texto", DataType.VARCHAR, 1000)
    ]
)


heap = HeapFile(
    "test_heap.dat"
)

rids = []

# 12 registros grandes -> varias páginas
for i in range(12):
    rid = heap.insert(
        Record([
            i,
            "X" * 900
        ]),
        schema_reopen
    )

    rids.append(rid)


print(
    "Paginas iniciales:",
    heap.page_count()
)


# Buscamos un registro de página 0
# y otro de página 1.
rid_page0 = next(
    rid
    for rid in rids
    if rid.page_id == 0
)

rid_page1 = next(
    rid
    for rid in rids
    if rid.page_id == 1
)


print(
    "Hueco pagina 0:",
    rid_page0
)

print(
    "Hueco pagina 1:",
    rid_page1
)


# Dejamos un hueco en dos páginas distintas.
heap.delete(rid_page0)
heap.delete(rid_page1)

paginas_antes = heap.page_count()

heap.close()


# --------------------------------------------------
# REABRIMOS
# --------------------------------------------------

heap = HeapFile(
    "test_heap.dat"
)


print()
print("ARCHIVO REABIERTO")


# Debe descubrir y usar el hueco de página 0.
rid_nuevo1 = heap.insert(
    Record([
        100,
        "A" * 900
    ]),
    schema_reopen
)

print(
    "Primer RID nuevo:",
    rid_nuevo1
)


# También debería ser capaz de descubrir
# el hueco que sigue existiendo en página 1.
rid_nuevo2 = heap.insert(
    Record([
        200,
        "B" * 900
    ]),
    schema_reopen
)

print(
    "Segundo RID nuevo:",
    rid_nuevo2
)

print(
    "Paginas antes:",
    paginas_antes
)

print(
    "Paginas despues:",
    heap.page_count()
)


assert rid_nuevo1.page_id == 0

assert rid_nuevo2.page_id == 1

assert heap.page_count() == paginas_antes


print()
print(
    "REUTILIZACION DESPUES DE REABRIR CORRECTA"
)


heap.close()

if os.path.exists("test_heap.dat"):
    os.remove("test_heap.dat")