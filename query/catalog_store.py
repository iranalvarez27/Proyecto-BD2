import json
import os

from common.types import Column, DataType, Schema
from index.bplus_tree import BPlusTree
from index.clustered_bplus_tree import ClusteredBPlusTree
from index.extendible_hash import ExtendibleHash
from index.rtree import RTree
from query.catalog import (Catalog, TableInfo, STORAGE_HEAP, STORAGE_SEQUENTIAL,
                           INDEX_BPLUS, INDEX_HASH, INDEX_CLUSTERED, INDEX_RTREE)
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile

ARCHIVO = "catalog.json"
VERSION = 1


def _ruta(data_dir: str) -> str:
    return os.path.join(data_dir, ARCHIVO)


def leer(data_dir: str) -> dict:
    ruta = _ruta(data_dir)
    if not os.path.exists(ruta):
        return {"version": VERSION, "tablas": {}}
    with open(ruta, encoding="utf-8") as f:
        contenido = json.load(f)
    contenido.setdefault("tablas", {})
    return contenido


def escribir(data_dir: str, contenido: dict) -> None:
    os.makedirs(data_dir, exist_ok=True)
    ruta = _ruta(data_dir)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(contenido, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ruta)


def entrada_de_tabla(info: TableInfo) -> dict:
    indices = []
    for columna, (indice, tipo) in info.indices.items():
        indices.append({
            "columna": columna,
            "tipo": tipo,
            "archivo": os.path.basename(indice.file_paths()[0]),
            "unique": bool(getattr(indice, "_unique", False)),
        })
    return {
        "storage": info.tipo_storage,
        "key_column": info.key_column,
        "archivos": [os.path.basename(p) for p in info.storage.file_paths()[:2]],
        "columnas": [{"name": c.name, "type": c.type.value, "size": c.size, "is_pk": c.is_pk}
                     for c in info.schema.columns],
        "indices": indices,
    }


def guardar_tabla(data_dir: str, info: TableInfo) -> None:
    contenido = leer(data_dir)
    contenido["tablas"][info.nombre] = entrada_de_tabla(info)
    escribir(data_dir, contenido)


def borrar_tabla(data_dir: str, nombre: str) -> None:
    contenido = leer(data_dir)
    if contenido["tablas"].pop(nombre, None) is not None:
        escribir(data_dir, contenido)


def _reconstruir_si_vacio(indice, tipo: str, info: TableInfo, columna: str) -> None:
    if tipo == INDEX_CLUSTERED or not indice.is_empty():
        return
    idx = info.schema.column_index(columna)
    pares = [(record.values[idx], rid) for rid, record in info.storage.scan_con_rid(info.schema)]
    if not pares:
        return
    if tipo == INDEX_BPLUS:
        pares.sort(key=lambda p: (p[0], p[1].page_id, p[1].slot_id))
    indice.bulk_load(pares)


def cargar(catalog: Catalog, pool, data_dir: str) -> list:
    agregadas = []
    for nombre, entrada in leer(data_dir)["tablas"].items():
        if not catalog.existe_tabla(nombre):
            columnas = [Column(c["name"], DataType(c["type"]), c["size"], c.get("is_pk", False))
                        for c in entrada["columnas"]]
            schema = Schema(nombre, columnas)
            archivos = entrada.get("archivos") or []
            datos = os.path.join(data_dir, archivos[0] if archivos else f"{nombre}.bin")
            if entrada["storage"] == STORAGE_SEQUENTIAL:
                aux = os.path.join(data_dir, archivos[1] if len(archivos) > 1 else f"{nombre}_aux.bin")
                storage = SequentialFile(pool, datos, aux, schema, entrada["key_column"])
            else:
                storage = HeapFile(pool, datos)
            catalog.register_table(nombre, schema, storage, entrada["storage"], entrada["key_column"])
            agregadas.append(nombre)

        info = catalog.get_table(nombre)
        for ind in entrada.get("indices", []):
            columna, tipo = ind["columna"], ind["tipo"]
            if catalog.tiene_indice(nombre, columna):
                continue
            ruta = os.path.join(data_dir, ind["archivo"])
            col = info.schema.columns[info.schema.column_index(columna)]
            if tipo == INDEX_CLUSTERED:
                indice = ClusteredBPlusTree(pool, info.storage, ruta)
            elif tipo == INDEX_HASH:
                indice = ExtendibleHash(pool, ruta)
            elif tipo == INDEX_RTREE:
                indice = RTree(pool, ruta)
            else:
                indice = BPlusTree(pool, ruta, col.type, unique=ind.get("unique", False))
            _reconstruir_si_vacio(indice, tipo, info, columna)
            catalog.register_index(nombre, columna, indice, tipo)
    return agregadas
