"""Índices persistentes de la tienda: texto (SPIMI y MiniLM en HNSW) e imágenes (ResNet-50 en HNSW e IVF)."""
from pathlib import Path

from index.inverted_index import IndiceInvertido
from index.vector.registro import CONSTRUCTORES
from query import catalog_store
from query.catalog import INDEX_INVERTED, INDEX_VECTOR
from recomendacion import semantico, visual
from recomendacion.preparar import RAIZ, asegurar_tabla, guardar_json, manifiesto
from recomendacion.repositorio import Repositorio


PARAMETROS = Path(__file__).resolve().parent / 'parametros.yaml'
# el mismo contenido de ecommerce_textos, con indice vectorial: una columna tiene un solo indice
TABLA_SEMANTICA = 'ecommerce_textos_semanticos'


def parametros_vectoriales() -> dict:
    """efSearch y nprobe calibrados por bench/experiments/tienda_vectores.py; sin archivo, los del motor."""
    if not PARAMETROS.exists():
        return {}
    import yaml
    datos = yaml.safe_load(PARAMETROS.read_text())
    return {metodo: {clave: datos[metodo][clave]} for metodo, clave in (('HNSW', 'efSearch'), ('IVF', 'nprobe'))
            if metodo in datos}


def preparar_indices(conexion):
    estado = manifiesto(conexion.data_dir)
    if not estado or not estado['catalogo_listo']:
        raise ValueError('Prepare primero el catálogo')
    visual.registrar()
    semantico.registrar()
    parametros = parametros_vectoriales()
    if (estado.get('indices_listos') and estado.get('firma_visual') == visual.FIRMA
            and estado.get('firma_semantica') == semantico.FIRMA
            and estado.get('parametros_vectoriales', {}) == parametros):
        columnas = (('ecommerce_textos', 'contenido'), (TABLA_SEMANTICA, 'contenido'),
                    ('ecommerce_imagenes_hnsw', 'ruta'), ('ecommerce_imagenes_ivf', 'ruta'))
        if all(conexion.catalog.existe_tabla(t) and conexion.catalog.tiene_indice(t, c) for t, c in columnas):
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

    # texto semantico: embeddings MiniLM de nombre + descripcion en HNSW
    asegurar_tabla(conexion, TABLA_SEMANTICA, 'id INT PRIMARY KEY, contenido VARCHAR(3500)')
    filas = repo.ejecutar('SELECT * FROM ecommerce_textos ORDER BY id')
    if len(repo.ejecutar(f'SELECT id FROM {TABLA_SEMANTICA}')) != len(filas):
        repo.ejecutar(f'DROP TABLE {TABLA_SEMANTICA}')
        asegurar_tabla(conexion, TABLA_SEMANTICA, 'id INT PRIMARY KEY, contenido VARCHAR(3500)')
        for f in filas:
            repo.insertar(TABLA_SEMANTICA, [f['id'], f['contenido']])
    embeddings = semantico.vectores_catalogo([f['id'] for f in filas], [f['contenido'] for f in filas],
                                             Path(conexion.data_dir) / 'ecommerce_vectores_texto.npz')
    info = conexion.catalog.get_table(TABLA_SEMANTICA)
    registros = list(info.storage.scan_con_rid(info.schema))
    indice = CONSTRUCTORES['HNSW']([rid for rid, _ in registros], [embeddings[r.values[0]] for _, r in registros],
                                   rutas=[r.values[1] for _, r in registros], extractor_nombre='minilm')
    indice.guardar(str(Path(conexion.data_dir) / f'{TABLA_SEMANTICA}_contenido_hnsw_vector.npz'))
    conexion.catalog.register_index(info.nombre, 'contenido', indice, INDEX_VECTOR)
    catalog_store.guardar_tabla(conexion.data_dir, info)

    imagenes = repo.ejecutar('SELECT * FROM ecommerce_imagenes_hnsw ORDER BY id')
    vectores = visual.vectores_catalogo([r['ruta'] for r in imagenes], [RAIZ / r['ruta'] for r in imagenes],
                                        Path(conexion.data_dir) / 'ecommerce_vectores_cnn.npz')
    for metodo in ('HNSW', 'IVF'):
        info = conexion.catalog.get_table('ecommerce_imagenes_' + metodo.lower())
        registros = list(info.storage.scan_con_rid(info.schema))
        indice = CONSTRUCTORES[metodo](
            [rid for rid, _ in registros], [vectores[r.values[1]] for _, r in registros],
            rutas=[r.values[1] for _, r in registros], extractor_nombre='cnn', **parametros.get(metodo, {}))
        indice.guardar(str(Path(conexion.data_dir) / f'{info.nombre}_ruta_{metodo.lower()}_vector.npz'))
        conexion.catalog.register_index(info.nombre, 'ruta', indice, INDEX_VECTOR)
        catalog_store.guardar_tabla(conexion.data_dir, info)
    estado.update(indices_listos=True, firma_visual=visual.FIRMA, firma_semantica=semantico.FIRMA,
                  dimension=visual.DIMENSION, parametros_vectoriales=parametros)
    for viejo in ('n_modelo', 'firma_modelo', 'vectores_sin_patrones'):
        estado.pop(viejo, None)
    guardar_json(Path(conexion.data_dir) / 'ecommerce_manifest.json', estado)
    return estado
