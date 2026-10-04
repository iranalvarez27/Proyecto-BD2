import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage.heap_file import HeapFile
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from common.record import Record
from common.types import Schema, Column, DataType


def _heap(path) -> HeapFile:
    return HeapFile(BufferPool(FileManager()), str(path))


def test_reutilizacion_de_espacio(tmp_path):
    schema = Schema(table_name="alumnos", columns=[
        Column("id", DataType.INT, 4, is_pk=True),
        Column("nombre", DataType.VARCHAR, 30),
        Column("edad", DataType.SMALLINT, 2),
    ])
    heap = _heap(tmp_path / "heap.dat")

    heap.insert(Record([1, "Ana", 20]), schema)
    rid2 = heap.insert(Record([2, "Pedro", 21]), schema)
    heap.insert(Record([3, "Maria", 22]), schema)

    heap.delete(rid2)
    assert heap.read(rid2, schema) is None

    rid4 = heap.insert(Record([4, "Luis", 23]), schema)
    assert heap.read(rid4, schema) is not None
    assert heap.read(rid4, schema).values[0] == 4

    keys = [r.values[0] for r in heap.scan(schema)]
    assert 1 in keys
    assert 2 not in keys
    assert 3 in keys
    assert 4 in keys

    heap.close()


def test_reusable_con_tamanos_variables(tmp_path):
    schema = Schema(table_name="datos", columns=[
        Column("id", DataType.INT, 4, is_pk=True),
        Column("texto", DataType.VARCHAR, 4080),
    ])
    heap = _heap(tmp_path / "heap.dat")

    rids = [heap.insert(Record([i, "X" * 900]), schema) for i in range(12)]

    rid_eliminado = rids[0]
    heap.delete(rid_eliminado)

    heap.insert(Record([100, "G" * 4078]), schema)
    rid_pequeno = heap.insert(Record([200, "hola"]), schema)

    assert heap.read(rid_pequeno, schema) is not None
    assert rid_pequeno.page_id == rid_eliminado.page_id

    heap.close()


def test_reutilizacion_despues_de_reabrir(tmp_path):
    schema = Schema(table_name="datos", columns=[
        Column("id", DataType.INT, 4, is_pk=True),
        Column("texto", DataType.VARCHAR, 1000),
    ])
    path = tmp_path / "heap.dat"
    heap = _heap(path)

    rids = [heap.insert(Record([i, "X" * 900]), schema) for i in range(12)]
    rid_page0 = next(rid for rid in rids if rid.page_id == 0)
    rid_page1 = next(rid for rid in rids if rid.page_id == 1)
    heap.delete(rid_page0)
    heap.delete(rid_page1)

    paginas_antes = heap.page_count()
    heap.close()

    heap = _heap(path)
    rid_nuevo1 = heap.insert(Record([100, "A" * 900]), schema)
    rid_nuevo2 = heap.insert(Record([200, "B" * 900]), schema)

    assert rid_nuevo1.page_id == 0
    assert rid_nuevo2.page_id == 1
    assert heap.page_count() == paginas_antes

    heap.close()


def test_espacio_libre_sin_eliminar(tmp_path):
    schema = Schema(table_name="datos", columns=[
        Column("id", DataType.INT, 4, is_pk=True),
        Column("texto", DataType.VARCHAR, 2000),
    ])
    path = tmp_path / "heap.dat"
    heap = _heap(path)

    heap.insert(Record([1, "A" * 1500]), schema)
    heap.insert(Record([2, "B" * 1500]), schema)
    heap.insert(Record([3, "C" * 1900]), schema)
    heap.insert(Record([4, "D" * 1900]), schema)

    assert heap.page_count() == 2
    heap.close()

    heap = _heap(path)
    rid_pequeno = heap.insert(Record([5, "E" * 500]), schema)

    assert rid_pequeno.page_id == 0
    assert heap.page_count() == 2

    heap.close()
