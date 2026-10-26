import argparse
import csv
import os
import re
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.page import HEADER_SIZE, PAGE_SIZE, SLOT_SIZE
from common.record import LENGTH_PREFIX_SIZE, Record
from common.types import DataType
from engine.buffer_pool import BufferPool
from engine.file_manager import FileManager
from index.inverted_index import IndiceInvertido
from index.spimi import MAX_POSTINGS_POR_BLOQUE
from query import catalog_store
from query.catalog import INDEX_INVERTED, Catalog
from query.conexion import Conexion
from query.tokens import KEYWORDS
from text.preprocesamiento import IDIOMA_POR_DEFECTO, IDIOMAS
from transaction.manager import TransactionManager

MAX_REGISTRO = PAGE_SIZE - HEADER_SIZE - SLOT_SIZE
MAX_VARCHAR_METADATA = 200
COLUMNA_ID = "id"
COLUMNA_CONTENIDO = "contenido"
TAMANOS_BENCHMARK = (1_000, 10_000, 100_000)
INT_MIN, INT_MAX = -2**31, 2**31 - 1
_TAMANO_FIJO = {DataType.INT: 4, DataType.DOUBLE: 8}


def nombre_columna(nombre: str) -> str:
    limpio = re.sub(r"[^a-z0-9_]+", "_", nombre.strip().lower()).strip("_") or "columna"
    if limpio[0].isdigit():
        limpio = "c_" + limpio
    if limpio in KEYWORDS or limpio in (COLUMNA_ID, COLUMNA_CONTENIDO):
        limpio += "_"
    return limpio


def recortar_utf8(texto: str, max_bytes: int) -> str:
    crudo = texto.encode("utf-8")
    if len(crudo) <= max_bytes:
        return texto
    return crudo[:max_bytes].decode("utf-8", errors="ignore")


def leer_csv(ruta: str, columnas_texto: list, columna_id: str | None = None, columnas_metadata=(),
             limite: int | None = None) -> list:
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    filas = []
    vistos = set()
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        faltantes = [c for c in [*columnas_texto, *columnas_metadata, *([columna_id] if columna_id else [])]
                     if c not in (lector.fieldnames or [])]
        if faltantes:
            raise ValueError(f"columnas que no estan en el CSV: {', '.join(faltantes)} "
                             f"(disponibles: {', '.join(lector.fieldnames or [])})")
        for fila in lector:
            contenido = " ".join(fila[c].strip() for c in columnas_texto if fila[c] and fila[c].strip())
            if not contenido:
                continue
            if columna_id:
                doc_id = int(fila[columna_id])
            else:
                doc_id = len(filas) + 1
            if doc_id in vistos:
                raise ValueError(f"id repetido en el CSV: {doc_id}")
            vistos.add(doc_id)
            filas.append({COLUMNA_ID: doc_id, COLUMNA_CONTENIDO: contenido,
                          **{c: (fila[c] or "").strip() for c in columnas_metadata}})
            if limite is not None and len(filas) >= limite:
                break
    return filas


def _es_int(valor: str) -> bool:
    try:
        return INT_MIN <= int(valor) <= INT_MAX
    except ValueError:
        return False


def _es_float(valor: str) -> bool:
    try:
        float(valor)
        return True
    except ValueError:
        return False


def inferir_tipo(valores: list) -> tuple:
    if valores and all(_es_int(v) for v in valores):
        return DataType.INT, 4
    if valores and all(_es_float(v) for v in valores):
        return DataType.DOUBLE, 8
    largo = max((len(v.encode("utf-8")) for v in valores), default=1)
    return DataType.VARCHAR, max(1, min(largo, MAX_VARCHAR_METADATA))


def preparar(filas: list, columnas_metadata=()) -> tuple:
    if not filas:
        raise ValueError("no hay documentos con contenido para cargar")
    metadata = []
    for original in columnas_metadata:
        tipo, tamano = inferir_tipo([f[original] for f in filas])
        metadata.append((original, nombre_columna(original), tipo, tamano))
    nombres = [n for _o, n, _t, _s in metadata]
    if len(set(nombres)) != len(nombres):
        raise ValueError(f"dos columnas de metadata quedan con el mismo nombre: {nombres}")

    ocupado = 4 + LENGTH_PREFIX_SIZE
    for _o, _n, tipo, tamano in metadata:
        ocupado += _TAMANO_FIJO.get(tipo, tamano + LENGTH_PREFIX_SIZE)
    presupuesto = MAX_REGISTRO - ocupado
    if presupuesto < 1:
        raise ValueError("la metadata ocupa toda la pagina: no queda espacio para el contenido")
    largo_contenido = max(len(f[COLUMNA_CONTENIDO].encode("utf-8")) for f in filas)
    tamano_contenido = min(presupuesto, largo_contenido)

    columnas = [(COLUMNA_ID, DataType.INT, 4, True), (COLUMNA_CONTENIDO, DataType.VARCHAR, tamano_contenido, False)]
    columnas += [(n, t, s, False) for _o, n, t, s in metadata]

    recortados = 0
    valores = []
    for fila in filas:
        contenido = recortar_utf8(fila[COLUMNA_CONTENIDO], tamano_contenido)
        if contenido != fila[COLUMNA_CONTENIDO]:
            recortados += 1
        registro = [fila[COLUMNA_ID], contenido]
        for original, _n, tipo, tamano in metadata:
            valor = fila[original]
            if tipo == DataType.INT:
                registro.append(int(valor))
            elif tipo == DataType.DOUBLE:
                registro.append(float(valor))
            else:
                registro.append(recortar_utf8(valor, tamano))
        valores.append(registro)
    return columnas, valores, recortados


def abrir_motor(data_dir: str) -> Conexion:
    os.makedirs(data_dir, exist_ok=True)
    pool = BufferPool(FileManager())
    catalog = Catalog()
    catalog_store.cargar(catalog, pool, data_dir)
    tmp_dir = os.path.join(data_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return Conexion(catalog, TransactionManager(pool=pool), tmp_dir=tmp_dir, pool=pool, data_dir=data_dir)


def _ejecutar(conexion: Conexion, sql: str) -> None:
    resultado = conexion.execute(sql)
    if not resultado.ok:
        raise RuntimeError(f"{sql[:80]}...: {resultado.error}")


def cargar_tabla(conexion: Conexion, tabla: str, columnas: list, valores: list, idioma: str = IDIOMA_POR_DEFECTO,
                 stemming: bool = True, max_postings_bloque: int = MAX_POSTINGS_POR_BLOQUE,
                 reemplazar: bool = False) -> dict:
    if idioma not in IDIOMAS:
        raise ValueError(f"idioma '{idioma}' no soportado (disponibles: {', '.join(IDIOMAS)})")
    catalog = conexion.catalog
    if catalog.existe_tabla(tabla):
        if not reemplazar:
            raise ValueError(f"la tabla '{tabla}' ya existe (usa reemplazar para volver a cargarla)")
        _ejecutar(conexion, f"DROP TABLE {tabla}")

    definicion = ", ".join(
        f"{n} {t.value}" + (f"({s})" if t == DataType.VARCHAR else "") + (" PRIMARY KEY" if pk else "")
        for n, t, s, pk in columnas)
    _ejecutar(conexion, f"CREATE TABLE {tabla} ({definicion})")

    inicio = time.perf_counter()
    info = catalog.get_table(tabla)
    claves = []
    pares = []
    for registro in valores:
        rid = info.storage.insert(Record(registro), info.schema)
        claves.append((registro[0], rid))
        pares.append((registro[1], rid))
    indice_pk, _tipo = catalog.get_indice(tabla, COLUMNA_ID)
    claves.sort(key=lambda p: (p[0], p[1].page_id, p[1].slot_id))
    indice_pk.bulk_load(claves)
    tiempo_carga = time.perf_counter() - inicio

    inicio = time.perf_counter()
    base = os.path.join(conexion.data_dir, f"{tabla}_{COLUMNA_CONTENIDO}_inverted")
    indice = IndiceInvertido(conexion.pool, base, idioma=idioma, stemming=stemming,
                             max_postings_bloque=max_postings_bloque)
    indice.bulk_load(pares)
    catalog.register_index(tabla, COLUMNA_CONTENIDO, indice, INDEX_INVERTED)
    catalog_store.guardar_tabla(conexion.data_dir, info)
    tiempo_indice = time.perf_counter() - inicio

    return {"tabla": tabla, "documentos": len(valores), "segundos_carga": round(tiempo_carga, 3),
            "segundos_indice": round(tiempo_indice, 3), **indice.estadisticas}


def exportar_csv(ruta: str, columnas: list, valores: list) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow([n for n, *_ in columnas])
        escritor.writerows(valores)


def etiqueta_tamano(n: int) -> str:
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}m"
    if n % 1000 == 0:
        return f"{n // 1000}k"
    return str(n)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Carga documentos de un CSV a una tabla y construye su indice invertido (SPIMI)")
    parser.add_argument("csv")
    parser.add_argument("--texto", nargs="+", required=True)
    parser.add_argument("--id")
    parser.add_argument("--metadata", nargs="*", default=[])
    parser.add_argument("--tabla", default="documentos")
    parser.add_argument("--tamanos", nargs="*", type=int)
    parser.add_argument("--idioma", default=IDIOMA_POR_DEFECTO, choices=IDIOMAS)
    parser.add_argument("--sin-stemming", action="store_true")
    parser.add_argument("--bloque", type=int, default=MAX_POSTINGS_POR_BLOQUE)
    parser.add_argument("--data-dir", default=os.path.join(PROJECT_ROOT, "data"))
    parser.add_argument("--exportar")
    parser.add_argument("--reemplazar", action="store_true")
    args = parser.parse_args(argv)

    tamanos = sorted(set(args.tamanos)) if args.tamanos else None
    filas = leer_csv(args.csv, args.texto, args.id, args.metadata, limite=max(tamanos) if tamanos else None)
    print(f"{len(filas)} documentos leidos de {args.csv}")
    conexion = abrir_motor(args.data_dir)
    destinos = [(f"{args.tabla}_{etiqueta_tamano(n)}", n) for n in tamanos] if tamanos else [(args.tabla, len(filas))]

    for tabla, n in destinos:
        if n > len(filas):
            print(f"{tabla}: se omite, el CSV solo tiene {len(filas)} documentos")
            continue
        columnas, valores, recortados = preparar(filas[:n], args.metadata)
        resumen = cargar_tabla(conexion, tabla, columnas, valores, args.idioma, not args.sin_stemming,
                               args.bloque, args.reemplazar)
        print(f"{tabla}: {resumen['documentos']} documentos ({recortados} recortados a {columnas[1][2]} bytes), "
              f"carga {resumen['segundos_carga']}s, SPIMI {resumen['segundos_indice']}s con "
              f"{resumen['bloques']} bloque(s), {resumen['terminos']} terminos, {resumen['postings']} postings")
        if args.exportar:
            ruta = os.path.join(args.exportar, f"{tabla}.csv")
            exportar_csv(ruta, columnas, valores)
            print(f"{tabla}: copia exacta de lo cargado en {ruta}")
    conexion.pool.close_all()


if __name__ == "__main__":
    main()
