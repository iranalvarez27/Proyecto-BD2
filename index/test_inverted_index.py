import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from index.inverted_index import IndiceInvertido
from query import catalog_store
from query.catalog import INDEX_INVERTED, Catalog
from query.conexion import Conexion
from transaction.manager import TransactionManager

DOCUMENTOS = [
    (1, "La casa es grande"),
    (2, "El gato está en la casa"),
    (3, "La casa es bonita y grande"),
    (4, "El sol brilla sobre la casa"),
]


def _motor(data_dir: str):
    pool = BufferPool(FileManager())
    catalog = Catalog()
    catalog_store.cargar(catalog, pool, data_dir)
    conexion = Conexion(catalog, TransactionManager(pool=pool), pool=pool, data_dir=data_dir, tmp_dir=data_dir)
    return conexion, catalog, pool


def _ejecutar(conexion: Conexion, sql: str):
    resultado = conexion.execute(sql)
    assert resultado.ok, resultado.error
    return resultado


@pytest.fixture
def motor_con_indice(tmp_path):
    data_dir = str(tmp_path)
    conexion, catalog, pool = _motor(data_dir)
    _ejecutar(conexion, "CREATE TABLE docs (id INT PRIMARY KEY, contenido VARCHAR(200))")
    for doc_id, texto in DOCUMENTOS:
        _ejecutar(conexion, f"INSERT INTO docs VALUES ({doc_id}, '{texto}')")
    _ejecutar(conexion, "CREATE INDEX ON docs (contenido) USING INVERTED")
    return data_dir, conexion, catalog, pool


def test_create_index_construye_el_indice_invertido(motor_con_indice):
    data_dir, _conexion, catalog, _pool = motor_con_indice
    indice, tipo = catalog.get_indice("docs", "contenido")
    assert tipo == INDEX_INVERTED
    assert isinstance(indice, IndiceInvertido)
    assert all(os.path.exists(r) for r in indice.file_paths())

    assert indice.documentos.N == 4
    assert indice.lector.df("cas") == 4
    assert [d for d, _tf in indice.lector.postings("grand")] == [0, 2]
    assert indice.terminos_consulta("Casas grandes") == ["cas", "grand"]
    assert not indice.desactualizado


def test_catalogo_guarda_el_indice_invertido(motor_con_indice):
    data_dir, *_ = motor_con_indice
    with open(os.path.join(data_dir, "catalog.json"), encoding="utf-8") as f:
        entrada = json.load(f)["tablas"]["docs"]
    invertido = next(i for i in entrada["indices"] if i["tipo"] == INDEX_INVERTED)
    assert invertido == {"columna": "contenido", "tipo": "inverted", "archivo": "docs_contenido_inverted.dic",
                         "unique": False, "idioma": "spanish", "stemming": True}


def test_indice_se_recarga_al_reiniciar_sin_reconstruirse(motor_con_indice):
    data_dir, _conexion, _catalog, pool = motor_con_indice
    pool.close_all()
    ruta_pst = os.path.join(data_dir, "docs_contenido_inverted.pst")
    modificado = os.path.getmtime(ruta_pst)

    _conexion2, catalog2, _pool2 = _motor(data_dir)
    indice, tipo = catalog2.get_indice("docs", "contenido")
    assert tipo == INDEX_INVERTED
    assert indice.documentos.N == 4
    assert indice.lector.postings("sol") == [(3, 1)]
    assert os.path.getmtime(ruta_pst) == modificado


def test_indice_borrado_se_reconstruye_al_cargar(motor_con_indice):
    data_dir, _conexion, _catalog, pool = motor_con_indice
    pool.close_all()
    for ext in (".dic", ".pst", ".doc"):
        os.remove(os.path.join(data_dir, f"docs_contenido_inverted{ext}"))

    _conexion2, catalog2, _pool2 = _motor(data_dir)
    indice, _tipo = catalog2.get_indice("docs", "contenido")
    assert indice.documentos.N == 4
    assert indice.lector.df("cas") == 4


def test_insert_y_delete_marcan_el_indice_desactualizado(motor_con_indice):
    data_dir, conexion, catalog, pool = motor_con_indice
    _ejecutar(conexion, "INSERT INTO docs VALUES (5, 'Un perro en la casa')")
    indice, _tipo = catalog.get_indice("docs", "contenido")
    assert indice.desactualizado

    pool.close_all()
    _conexion2, catalog2, _pool2 = _motor(data_dir)
    assert catalog2.get_indice("docs", "contenido")[0].desactualizado


def test_rollback_deja_el_indice_al_dia(motor_con_indice):
    _data_dir, conexion, catalog, _pool = motor_con_indice
    _ejecutar(conexion, "BEGIN TRANSACTION")
    _ejecutar(conexion, "INSERT INTO docs VALUES (5, 'Un perro en la casa')")
    _ejecutar(conexion, "ROLLBACK")
    assert not catalog.get_indice("docs", "contenido")[0].desactualizado


def test_drop_table_borra_los_archivos_del_indice(motor_con_indice):
    data_dir, conexion, catalog, _pool = motor_con_indice
    rutas = catalog.get_indice("docs", "contenido")[0].file_paths()
    _ejecutar(conexion, "DROP TABLE docs")
    assert not any(os.path.exists(r) for r in rutas)


def test_inverted_solo_en_columnas_de_texto(motor_con_indice):
    _data_dir, conexion, *_ = motor_con_indice
    resultado = conexion.execute("CREATE INDEX ON docs (id) USING INVERTED")
    assert not resultado.ok


def test_match_bm25_y_score(motor_con_indice):
    _data_dir, conexion, *_ = motor_con_indice
    res = _ejecutar(
        conexion,
        "SELECT id, contenido, SCORE() AS relevancia FROM docs "
        "WHERE MATCH(contenido, 'casa grande') USING BM25 ORDER BY relevancia DESC",
    )
    assert len(res.filas) == 4
    # Documentos 1 ("La casa es grande") y 3 ("La casa es bonita y grande") contienen ambos terminos
    # Doc 1 es mas corto que Doc 3, por lo que BM25 le asigna mayor relevancia
    assert [f["id"] for f in res.filas[:2]] == [1, 3]
    assert res.filas[0]["relevancia"] > res.filas[1]["relevancia"] > res.filas[2]["relevancia"] > 0
    assert all("__score__" not in f for f in res.filas)
    assert res.texto is not None
    assert res.texto["metodo"] == "BM25"
    assert len(res.texto["resultados"]) == 4


def test_match_tfidf_con_select_estrella_y_limit(motor_con_indice):
    _data_dir, conexion, *_ = motor_con_indice
    res = _ejecutar(
        conexion,
        "SELECT *, SCORE() FROM docs WHERE MATCH(contenido, 'casa grande') USING TF_IDF LIMIT 2",
    )
    assert len(res.filas) == 2
    assert [f["id"] for f in res.filas] == [1, 3]
    assert "score" in res.filas[0]
    assert res.filas[0]["score"] > res.filas[1]["score"] > 0
    assert all("__score__" not in f for f in res.filas)


def test_match_combinado_con_and_y_order_by_columna(motor_con_indice):
    _data_dir, conexion, *_ = motor_con_indice
    res = _ejecutar(
        conexion,
        "SELECT id, SCORE() AS s FROM docs "
        "WHERE MATCH(contenido, 'casa grande') USING BM25 AND id > 1 "
        "ORDER BY id ASC",
    )
    assert [f["id"] for f in res.filas] == [2, 3, 4]
    # Doc 3 tiene ambos terminos ('cas' y 'grand'), por lo que su score es el mayor
    scores_por_id = {f["id"]: f["s"] for f in res.filas}
    assert scores_por_id[3] > scores_por_id[2] > 0


def test_match_reconstruye_indice_desactualizado_tras_insert(motor_con_indice):
    _data_dir, conexion, catalog, _pool = motor_con_indice
    _ejecutar(conexion, "INSERT INTO docs VALUES (5, 'Un perro ladra fuerte')")
    indice, _ = catalog.get_indice("docs", "contenido")
    assert indice.desactualizado

    res = _ejecutar(
        conexion,
        "SELECT id, contenido, SCORE() AS rel FROM docs WHERE MATCH(contenido, 'perro ladra') USING BM25",
    )
    assert not indice.desactualizado
    assert [f["id"] for f in res.filas] == [5]
    assert res.filas[0]["rel"] > 0

