"""Índices persistentes de la tienda: texto (SPIMI) e imágenes (ResNet-50 en HNSW e IVF)."""
from pathlib import Path

from index.inverted_index import IndiceInvertido
from index.vector.registro import CONSTRUCTORES
from query import catalog_store
from query.catalog import INDEX_INVERTED, INDEX_VECTOR
from recomendacion import visual
from recomendacion.preparar import RAIZ, guardar_json, manifiesto
from recomendacion.repositorio import Repositorio


def preparar_indices(conexion):
    estado = manifiesto(conexion.data_dir)
    if not estado or not estado['catalogo_listo']:
        raise ValueError('Prepare primero el catálogo')
    visual.registrar()
    if estado.get('indices_listos') and estado.get('firma_visual') == visual.FIRMA:
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
    vectores = visual.vectores_catalogo([r['ruta'] for r in imagenes], [RAIZ / r['ruta'] for r in imagenes],
                                        Path(conexion.data_dir) / 'ecommerce_vectores_cnn.npz')
    for metodo in ('HNSW', 'IVF'):
        info = conexion.catalog.get_table('ecommerce_imagenes_' + metodo.lower())
        registros = list(info.storage.scan_con_rid(info.schema))
        indice = CONSTRUCTORES[metodo](
            [rid for rid, _ in registros], [vectores[r.values[1]] for _, r in registros],
            rutas=[r.values[1] for _, r in registros], extractor_nombre='cnn')
        indice.guardar(str(Path(conexion.data_dir) / f'{info.nombre}_ruta_{metodo.lower()}_vector.npz'))
        conexion.catalog.register_index(info.nombre, 'ruta', indice, INDEX_VECTOR)
        catalog_store.guardar_tabla(conexion.data_dir, info)
    estado.update(indices_listos=True, firma_visual=visual.FIRMA, dimension=visual.DIMENSION)
    for viejo in ('n_modelo', 'firma_modelo', 'vectores_sin_patrones'):
        estado.pop(viejo, None)
    guardar_json(Path(conexion.data_dir) / 'ecommerce_manifest.json', estado)
    return estado
