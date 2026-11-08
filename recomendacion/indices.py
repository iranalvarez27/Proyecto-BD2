"""Índices persistentes con el modelo visual fijado en el manifiesto."""
import hashlib
from pathlib import Path

import numpy as np

from index.inverted_index import IndiceInvertido
from index.vector.registro import CONSTRUCTORES
from multimedia.bovw import Extractor
from query import catalog_store
from query.catalog import INDEX_INVERTED, INDEX_VECTOR
from recomendacion.preparar import RAIZ, guardar_json, manifiesto
from recomendacion.repositorio import Repositorio


def firma_modelo(extractor):
    h = hashlib.sha256()
    for arreglo in (extractor.codebook, extractor.idf):
        h.update(np.ascontiguousarray(arreglo).tobytes())
    h.update(str(extractor.meta).encode())
    return h.hexdigest()


def preparar_indices(conexion, n_modelo=100000):
    estado = manifiesto(conexion.data_dir)
    if not estado or not estado['catalogo_listo']:
        raise ValueError('Prepare primero el catálogo')
    extractor = Extractor('imagen', n_coleccion=n_modelo)
    firma = firma_modelo(extractor)
    if estado.get('indices_listos') and estado.get('firma_modelo') == firma:
        tablas = ('ecommerce_textos', 'ecommerce_imagenes_hnsw', 'ecommerce_imagenes_ivf')
        if all(conexion.catalog.tiene_indice(t, 'contenido' if t.endswith('textos') else 'ruta') for t in tablas):
            return estado
    estado['indices_listos'] = False
    guardar_json(Path(conexion.data_dir) / 'ecommerce_manifest.json', estado)
    repo = Repositorio(conexion)
    for columna, tipo in [('categoria', 'HASH'), ('subcategoria', 'HASH'), ('precio_centavos', 'BTREE')]:
        if not conexion.catalog.tiene_indice('ecommerce_productos', columna):
            repo.ejecutar(f'CREATE INDEX ON ecommerce_productos ({columna}) USING {tipo}')
    textos = conexion.catalog.get_table('ecommerce_textos')
    indice = IndiceInvertido(conexion.pool, str(Path(conexion.data_dir) / 'ecommerce_textos_contenido_inverted'), idioma='english')
    indice.idioma = 'english'
    indice.bulk_load([(r.values[1], rid) for rid, r in textos.storage.scan_con_rid(textos.schema)])
    conexion.catalog.register_index(textos.nombre, 'contenido', indice, INDEX_INVERTED)
    catalog_store.guardar_tabla(conexion.data_dir, textos)

    imagenes = repo.ejecutar('SELECT * FROM ecommerce_imagenes_hnsw ORDER BY id')
    vectores = {r['id']: extractor(RAIZ / r['ruta']) for r in imagenes}
    for metodo in ('HNSW', 'IVF'):
        info = conexion.catalog.get_table('ecommerce_imagenes_' + metodo.lower())
        registros = list(info.storage.scan_con_rid(info.schema))
        indice = CONSTRUCTORES[metodo](
            [rid for rid, _ in registros], [vectores[r.values[0]] for _, r in registros],
            rutas=[r.values[1] for _, r in registros], n_coleccion=n_modelo)
        indice.guardar(str(Path(conexion.data_dir) / f'{info.nombre}_ruta_{metodo.lower()}_vector.npz'))
        conexion.catalog.register_index(info.nombre, 'ruta', indice, INDEX_VECTOR)
        catalog_store.guardar_tabla(conexion.data_dir, info)
    estado.update(indices_listos=True, n_modelo=n_modelo, firma_modelo=firma,
                  dimension=len(extractor.idf), vectores_sin_patrones=sum(not np.any(v) for v in vectores.values()))
    guardar_json(Path(conexion.data_dir) / 'ecommerce_manifest.json', estado)
    return estado
