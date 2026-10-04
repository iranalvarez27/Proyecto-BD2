import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from common.record import Record
from common.types import Schema, Column, DataType
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from storage.sequential_file import SequentialFile, MAIN_FILE, AUX_FILE

SCHEMA = Schema(table_name="alumnos", columns=[
    Column("id", DataType.INT, 4, is_pk=True),
    Column("nombre", DataType.VARCHAR, 30),
    Column("edad", DataType.SMALLINT, 2),
])


def _seq(tmp_path, name: str = "seq", schema: Schema = SCHEMA) -> SequentialFile:
    return SequentialFile(
        BufferPool(FileManager()),
        str(tmp_path / f"{name}.dat"),
        str(tmp_path / f"{name}_aux.dat"),
        schema,
        "id",
    )


def test_eliminar_head_actualiza_busqueda(tmp_path):
    seq = _seq(tmp_path)
    seq.insert(Record([10, "Ana", 20]))
    seq.insert(Record([20, "Pedro", 21]))
    seq.insert(Record([30, "Maria", 22]))

    assert seq.delete(10) is not None

    assert seq.search(10) is None
    assert seq.search(20) is not None
    assert seq.search(30) is not None
    seq.close()


def test_eliminar_clave_inexistente(tmp_path):
    seq = _seq(tmp_path)
    seq.insert(Record([10, "Ana", 20]))
    seq.insert(Record([20, "Pedro", 21]))
    seq.insert(Record([30, "Maria", 22]))

    assert seq.delete(30) is not None
    assert seq.search(30) is None
    assert seq.delete(999) is None
    seq.close()


def test_insercion_mantiene_orden_en_los_extremos(tmp_path):
    seq = _seq(tmp_path)
    seq.insert(Record([20, "Pedro", 21]))
    seq.insert(Record([30, "Maria", 22]))
    seq.insert(Record([10, "Ana", 20]))
    seq.insert(Record([40, "Luis", 23]))

    keys = [r.values[0] for r in seq.scan()]
    assert keys == [10, 20, 30, 40]
    seq.close()


def test_multipagina_orden_y_reorganizacion(tmp_path):
    seq = _seq(tmp_path)
    for i in range(200, 0, -1):
        seq.insert(Record([i, "X" * 30, 20]))

    records = list(seq.scan())
    assert len(records) == 200
    assert [r.values[0] for r in records] == list(range(1, 201))

    seq.reorganize()

    records = list(seq.scan())
    assert len(records) == 200
    assert [r.values[0] for r in records] == list(range(1, 201))
    assert seq.page_count(AUX_FILE) == 0
    seq.close()


def test_persistencia_tras_reabrir(tmp_path):
    seq = _seq(tmp_path)
    for i in range(200, 0, -1):
        seq.insert(Record([i, "X" * 30, 20]))
    seq.close()

    seq2 = _seq(tmp_path)
    records = list(seq2.scan())
    assert len(records) == 200
    assert [r.values[0] for r in records] == list(range(1, 201))
    seq2.close()


def test_clave_duplicada_se_rechaza(tmp_path):
    seq = _seq(tmp_path)
    seq.insert(Record([10, "Ana", 20]))
    seq.insert(Record([20, "Pedro", 21]))
    seq.insert(Record([30, "Maria", 22]))

    with pytest.raises(ValueError):
        seq.insert(Record([20, "Otro Pedro", 25]))

    keys = [r.values[0] for r in seq.scan()]
    assert keys == [10, 20, 30]
    seq.close()


def test_reinsertar_pk_eliminada(tmp_path):
    seq = _seq(tmp_path)
    seq.insert(Record([10, "Ana", 20]))
    seq.insert(Record([20, "Pedro", 21]))
    seq.insert(Record([30, "Maria", 22]))

    assert seq.delete(20) is not None
    seq.insert(Record([20, "Pedro Nuevo", 25]))

    record_20 = seq.search(20)
    assert record_20 is not None
    assert record_20.values[1] == "Pedro Nuevo"
    seq.close()


def test_search_en_main_y_en_aux(tmp_path):
    seq = _seq(tmp_path)
    for i in range(1, 201):
        seq.insert(Record([i, "X" * 30, 20]))

    assert seq.search(1).values[0] == 1
    assert seq.search(100).values[0] == 100
    assert seq.search(200).values[0] == 200
    assert seq.search(999) is None

    assert seq.delete(150) is not None
    seq.insert(Record([150, "Nuevo", 25]))
    assert seq.search(150) is not None
    assert seq.search(150).values[0] == 150
    assert seq.aux_record_count() == 1

    assert seq.delete(100) is not None
    assert seq.search(100) is None
    seq.close()


def test_optimizacion_insercion_main_vs_aux(tmp_path):
    seq = _seq(tmp_path)
    seq.insert(Record([10, "A", 20]))
    seq.insert(Record([20, "B", 20]))
    seq.insert(Record([30, "C", 20]))
    seq.insert(Record([40, "D", 20]))
    assert seq.aux_record_count() == 0

    assert seq.delete(40) is not None
    seq.insert(Record([35, "E", 20]))
    assert seq.aux_record_count() == 1

    seq.insert(Record([50, "F", 20]))
    assert seq.aux_record_count() == 1

    keys = [r.values[0] for r in seq.scan()]
    assert keys == [10, 20, 30, 35, 50]
    seq.close()


def test_archivo_logicamente_vacio_acepta_insert(tmp_path):
    seq = _seq(tmp_path)
    seq.insert(Record([10, "A", 20]))
    seq.insert(Record([20, "B", 20]))
    assert seq.delete(10) is not None
    assert seq.delete(20) is not None

    seq.insert(Record([5, "C", 20]))
    assert seq.search(5) is not None
    assert seq.search(5).values[0] == 5
    seq.close()
