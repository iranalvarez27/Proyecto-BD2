import csv
import gzip
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data.preparar_amazon import limpiar, preparar, producto_completo


def _item(asin, precio=99.5, descripcion=("Fast laptop",), features=("8GB RAM",), resenas=30, imagenes=True):
    return {
        "main_category": "Computers", "title": f"Laptop {asin}", "average_rating": 4.2, "rating_number": resenas,
        "features": list(features), "description": list(descripcion), "price": precio,
        "images": [{"thumb": "t.jpg", "large": f"{asin}.jpg", "variant": "MAIN", "hi_res": f"{asin}_hd.jpg"}]
        if imagenes else [],
        "videos": [], "store": "HP", "categories": ["Electronics", "Computers & Accessories", "Laptops"],
        "details": {"Brand": "HP"}, "parent_asin": asin, "bought_together": None,
    }


def _gz(ruta, filas):
    with gzip.open(ruta, "wt", encoding="utf-8") as f:
        for fila in filas:
            f.write(json.dumps(fila) + "\n")


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_producto_completo_filtra_incompletos():
    assert producto_completo(_item("A1"), 20)["marca"] == "HP"
    assert producto_completo(_item("A1", precio="None"), 20) is None
    assert producto_completo(_item("A1", descripcion=(), features=()), 20) is None
    assert producto_completo(_item("A1", imagenes=False), 20) is None
    assert producto_completo(_item("A1", resenas=3), 20) is None
    assert producto_completo(_item("A1", descripcion=()), 20)["caracteristicas"] == "8GB RAM"


def test_limpiar_quita_html_y_espacios():
    assert limpiar(["<p>Great&nbsp;sound</p>", "", "  for   music "]) == "Great sound for music"
    assert limpiar(None) == ""


def test_preparar_genera_los_tres_csv(tmp_path):
    items = [_item(f"A{i}") for i in range(30)] + [_item("SINPRECIO", precio=None), _item("A0")]
    _gz(tmp_path / "meta.jsonl.gz", items)
    resenas = [{"parent_asin": f"A{i % 5}", "user_id": f"U{i % 3}", "rating": 5.0, "timestamp": i,
                "verified_purchase": True} for i in range(12)]
    resenas.append({"parent_asin": "OTRO", "user_id": "U9", "rating": 1.0, "timestamp": 1, "verified_purchase": False})
    _gz(tmp_path / "resenas.jsonl.gz", resenas)

    salida = tmp_path / "amazon"
    resumen = preparar(str(tmp_path / "meta.jsonl.gz"), str(tmp_path / "resenas.jsonl.gz"), str(salida),
                       n=10, min_resenas=20, semilla=1)
    assert resumen["productos_completos"] == 30
    assert resumen["productos_elegidos"] == 10

    productos = _leer(salida / "productos.csv")
    assert [p["id"] for p in productos] == [str(i) for i in range(1, 11)]
    assert len({p["asin"] for p in productos}) == 10
    assert productos[0]["subcategoria"] == "Laptops"
    imagenes = _leer(salida / "imagenes.csv")
    assert imagenes[0]["url"] == f"{productos[0]['asin']}.jpg"

    elegidos = {p["asin"]: p["id"] for p in productos}
    esperadas = sum(1 for r in resenas if r["parent_asin"] in elegidos)
    compras = _leer(salida / "compras.csv")
    assert len(compras) == resumen["compras"] == esperadas
    assert {c["producto_id"] for c in compras} <= set(elegidos.values())

    repetido = preparar(str(tmp_path / "meta.jsonl.gz"), None, str(tmp_path / "otra"), n=10, min_resenas=20, semilla=1)
    assert repetido["productos_elegidos"] == 10
    assert _leer(tmp_path / "otra" / "productos.csv") == productos
