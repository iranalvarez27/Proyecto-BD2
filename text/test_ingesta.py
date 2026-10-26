import csv
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from common.types import DataType
from query.catalog import INDEX_INVERTED
from text.ingesta import (MAX_REGISTRO, abrir_motor, cargar_tabla, etiqueta_tamano, leer_csv, main,
                          nombre_columna, preparar, recortar_utf8)

PRODUCTOS = [
    {"sku": "10", "nombre": "Laptop HP 15", "descripcion": "Laptop with 8GB RAM and fast battery charging",
     "categoria": "Computers", "precio": "1299.90", "stock": "4"},
    {"sku": "11", "nombre": "Wireless mouse", "descripcion": "Ergonomic mouse with long battery life",
     "categoria": "Accessories", "precio": "25", "stock": "120"},
    {"sku": "12", "nombre": "Gaming laptop", "descripcion": "",
     "categoria": "Computers", "precio": "2100.5", "stock": "2"},
    {"sku": "13", "nombre": "", "descripcion": "", "categoria": "Empty", "precio": "1", "stock": "1"},
    {"sku": "14", "nombre": "Keyboard", "descripcion": "Mechanical keyboard, ñandú edition " + "click " * 900,
     "categoria": "Accessories", "precio": "89.99", "stock": "0"},
]


@pytest.fixture
def csv_productos(tmp_path):
    ruta = tmp_path / "productos.csv"
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(PRODUCTOS[0]))
        escritor.writeheader()
        escritor.writerows(PRODUCTOS)
    return str(ruta)


def test_leer_csv_une_columnas_de_texto_y_omite_vacios(csv_productos):
    filas = leer_csv(csv_productos, ["nombre", "descripcion"], "sku", ["categoria", "precio"])
    assert [f["id"] for f in filas] == [10, 11, 12, 14]
    assert filas[0]["contenido"] == "Laptop HP 15 Laptop with 8GB RAM and fast battery charging"
    assert filas[2]["contenido"] == "Gaming laptop"
    assert filas[0]["precio"] == "1299.90"
    assert len(leer_csv(csv_productos, ["nombre"], limite=2)) == 2
    assert [f["id"] for f in leer_csv(csv_productos, ["nombre"])] == [1, 2, 3, 4]


def test_leer_csv_avisa_columnas_inexistentes_e_ids_repetidos(csv_productos, tmp_path):
    with pytest.raises(ValueError, match="no estan en el CSV"):
        leer_csv(csv_productos, ["titulo"])
    repetido = tmp_path / "rep.csv"
    repetido.write_text("id,texto\n1,hola mundo\n1,otra vez\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repetido"):
        leer_csv(str(repetido), ["texto"], "id")


def test_preparar_infiere_tipos_y_recorta_lo_que_no_cabe(csv_productos):
    filas = leer_csv(csv_productos, ["nombre", "descripcion"], "sku", ["categoria", "precio", "stock"])
    columnas, valores, recortados = preparar(filas, ["categoria", "precio", "stock"])
    tipos = {n: t for n, t, _s, _pk in columnas}
    assert tipos == {"id": DataType.INT, "contenido": DataType.VARCHAR, "categoria": DataType.VARCHAR,
                     "precio": DataType.DOUBLE, "stock": DataType.INT}
    assert columnas[0][3] is True
    assert recortados == 1
    assert max(len(v[1].encode("utf-8")) for v in valores) == columnas[1][2] < MAX_REGISTRO
    assert valores[0][2:] == ["Computers", 1299.9, 4]
    assert valores[-1][1].startswith("Keyboard Mechanical keyboard, ñandú edition click")


def test_cargar_tabla_crea_tabla_e_indice(csv_productos, tmp_path):
    data_dir = str(tmp_path / "data")
    conexion = abrir_motor(data_dir)
    columnas, valores, _ = preparar(leer_csv(csv_productos, ["nombre", "descripcion"], "sku", ["categoria", "precio"]),
                                    ["categoria", "precio"])
    resumen = cargar_tabla(conexion, "productos", columnas, valores, idioma="english", max_postings_bloque=5)
    assert resumen["documentos"] == 4 and resumen["bloques"] >= 2

    resultado = conexion.execute("SELECT * FROM productos WHERE precio > 100")
    assert resultado.ok, resultado.error
    assert sorted(f["id"] for f in resultado.filas) == [10, 12]

    indice, tipo = conexion.catalog.get_indice("productos", "contenido")
    assert tipo == INDEX_INVERTED and indice.idioma == "english"
    assert [d for d, _tf in indice.lector.postings("laptop")] == [0, 2]
    assert indice.lector.df("batteri") == 2
    conexion.pool.close_all()

    reabierta = abrir_motor(data_dir)
    indice2, _ = reabierta.catalog.get_indice("productos", "contenido")
    assert indice2.idioma == "english" and indice2.documentos.N == 4
    assert reabierta.execute("SELECT * FROM productos WHERE id = 14").filas[0]["categoria"] == "Accessories"


def test_cargar_tabla_existente(csv_productos, tmp_path):
    conexion = abrir_motor(str(tmp_path / "data"))
    columnas, valores, _ = preparar(leer_csv(csv_productos, ["nombre"]))
    cargar_tabla(conexion, "docs", columnas, valores)
    with pytest.raises(ValueError, match="ya existe"):
        cargar_tabla(conexion, "docs", columnas, valores)
    assert cargar_tabla(conexion, "docs", columnas[:], valores[:2], reemplazar=True)["documentos"] == 2


def test_main_genera_las_muestras_y_las_exporta(csv_productos, tmp_path, capsys):
    data_dir = str(tmp_path / "data")
    exportar = str(tmp_path / "muestras")
    main([csv_productos, "--texto", "nombre", "descripcion", "--id", "sku", "--metadata", "categoria", "precio",
          "--tabla", "productos", "--tamanos", "2", "4", "50", "--idioma", "english", "--data-dir", data_dir,
          "--exportar", exportar])
    salida = capsys.readouterr().out
    assert "productos_50: se omite" in salida

    conexion = abrir_motor(data_dir)
    assert conexion.catalog.existe_tabla("productos_2") and conexion.catalog.existe_tabla("productos_4")
    with open(os.path.join(exportar, "productos_4.csv"), encoding="utf-8") as f:
        filas = list(csv.reader(f))
    assert filas[0] == ["id", "contenido", "categoria", "precio"]
    assert len(filas) == 5


def test_utilidades():
    assert nombre_columna("Precio (USD)") == "precio_usd"
    assert nombre_columna("select") == "select_"
    assert nombre_columna("2024 ventas") == "c_2024_ventas"
    assert nombre_columna("contenido") == "contenido_"
    assert recortar_utf8("ñandú", 3) == "ña"
    assert recortar_utf8("ñandú", 6) == "ñand"
    assert recortar_utf8("hola", 10) == "hola"
    assert [etiqueta_tamano(n) for n in (1000, 10_000, 100_000, 1500)] == ["1k", "10k", "100k", "1500"]
