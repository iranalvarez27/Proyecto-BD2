"""Consultas de contenido y catálogo ejecutadas mediante el motor SQL."""
from collections import OrderedDict
import json
from pathlib import Path
import threading
import time
from urllib.parse import quote
import uuid

from multimedia.bovw import Extractor
from recomendacion.fusion import MODALIDADES, fusionar
from recomendacion.indices import firma_modelo
from recomendacion.preparar import manifiesto
from recomendacion.repositorio import Repositorio, literal

PESOS = {'visual': .3, 'texto': .3, 'metadata': .2, 'compras': .2}


class Servicio:
    def __init__(self, conexion):
        self.conexion = conexion
        self.lock = threading.RLock()
        self.busquedas = OrderedDict()
        self.modelo = None
        self.firma_archivos = None

    def estado(self):
        meta = manifiesto(self.conexion.data_dir) or {}
        indices = {}
        for tabla in self.conexion.catalog.listar_tablas():
            if tabla.startswith('ecommerce_'):
                info = self.conexion.catalog.get_table(tabla)
                indices[tabla] = {col: getattr(idx, 'metodo', tipo) for col, (idx, tipo) in info.indices.items()}
        return {**meta, 'productos': len(meta.get('asins', [])), 'indices': indices,
                'listo': bool(meta.get('catalogo_listo') and meta.get('indices_listos')),
                'datos_comerciales': 'Inventario y compras de demostración simulados'}

    def verificar(self):
        estado = self.estado()
        if not estado['listo']:
            raise ValueError('Prepare el catálogo con python3 -m recomendacion.preparar y reinicie el backend')
        from multimedia import config
        directorio = config.directorio_modelo('imagen')
        archivos = [directorio / 'meta.json', directorio / 'codebook.npy',
                    directorio / 'colecciones' / str(estado['n_modelo']) / 'idf.npy']
        firma = (estado['firma_modelo'], tuple(p.stat().st_mtime_ns for p in archivos))
        if self.firma_archivos != firma:
            modelo = Extractor('imagen', n_coleccion=estado['n_modelo'])
            if firma_modelo(modelo) != estado['firma_modelo']:
                raise ValueError('El modelo visual cambió. Reconstruya los índices de e-commerce antes de consultar.')
            self.modelo, self.firma_archivos = modelo, firma
        return estado

    def productos(self, repo, ids=None):
        condicion = ''
        if ids is not None:
            if not ids:
                return {}
            condicion = ' WHERE id IN (' + ','.join(str(int(i)) for i in ids) + ')'
        filas = repo.ejecutar('SELECT * FROM ecommerce_productos' + condicion)
        imagenes = repo.ejecutar('SELECT * FROM ecommerce_imagenes_hnsw' + condicion)
        rutas = {r['id']: r['ruta'] for r in imagenes}
        for p in filas:
            p['ruta'] = rutas.get(p['id'], '')
            p['media_url'] = '/api/media/' + quote(p['ruta'], safe='/') if p['ruta'] else None
        return {p['id']: p for p in filas}

    def detalle(self, pid):
        self.verificar()
        repo = Repositorio(self.conexion)
        p = self.productos(repo, [pid]).get(pid)
        if p is None:
            raise LookupError('Producto inexistente')
        texto = repo.ejecutar(f'SELECT contenido FROM ecommerce_textos WHERE id = {int(pid)}')
        return {**p, 'descripcion': texto[0]['contenido'] if texto else ''}

    def catalogo(self, category='', search='', limit=24, after_id=0, cursor='', min_price=None, max_price=None):
        estado = self.verificar()
        repo = Repositorio(self.conexion)
        filtros = []
        if category:
            filtros.append(f'categoria = {literal(category)}')
        if min_price is not None:
            filtros.append(f'precio_centavos >= {int(min_price)}')
        if max_price is not None:
            filtros.append(f'precio_centavos <= {int(max_price)}')
        categorias = repo.ejecutar('SELECT categoria FROM ecommerce_productos GROUP BY categoria')
        siguiente = None
        truncada = False
        if search.strip():
            clave = json.dumps([search, category, min_price, max_price, estado['firma_catalogo']])
            ahora = time.monotonic()
            for token in list(self.busquedas):
                if self.busquedas[token]['vence'] < ahora:
                    del self.busquedas[token]
            if cursor:
                token, posicion = cursor.rsplit('.', 1)
                consulta = self.busquedas.get(token)
                if consulta is None or consulta['clave'] != clave:
                    raise ValueError('La búsqueda expiró o sus filtros cambiaron. Reinicie la búsqueda.')
                inicio = int(posicion)
                if inicio < 0:
                    raise ValueError('Cursor inválido')
            else:
                token, inicio = uuid.uuid4().hex, 0
                hallados = repo.ejecutar(f'SELECT id, SCORE() AS relevancia FROM ecommerce_textos WHERE MATCH(contenido, {literal(search)}) USING BM25')
                permitidos = None
                if filtros:
                    permitidos = {p['id'] for p in repo.ejecutar('SELECT id FROM ecommerce_productos WHERE ' + ' AND '.join(filtros))}
                orden = sorted(hallados, key=lambda r: (-r['relevancia'], r['id']))
                ids = [r['id'] for r in orden if permitidos is None or r['id'] in permitidos]
                consulta = {'clave': clave, 'ids': ids[:500], 'truncada': len(ids) > 500, 'vence': ahora + 300}
                self.busquedas[token] = consulta
                while len(self.busquedas) > 64:
                    self.busquedas.popitem(last=False)
            ids = consulta['ids'][inicio:inicio + limit]
            productos = self.productos(repo, ids)
            filas = [productos[i] for i in ids if i in productos]
            if inicio + limit < len(consulta['ids']):
                siguiente = f'{token}.{inicio + limit}'
            truncada = consulta['truncada']
        else:
            filtros.append(f'id > {int(after_id)}')
            filas_id = repo.ejecutar('SELECT id FROM ecommerce_productos WHERE ' + ' AND '.join(filtros) + f' ORDER BY id LIMIT {limit + 1}')
            ids = [p['id'] for p in filas_id[:limit]]
            productos = self.productos(repo, ids)
            filas = [productos[i] for i in ids]
            if len(filas_id) > limit:
                siguiente = str(ids[-1])
        return {'productos': filas, 'categorias': sorted(r['categoria'] for r in categorias),
                'next_cursor': siguiente, 'busqueda_acotada': truncada, 'trazas': repo.trazas}

    def recomendar(self, pid, k=10, pesos=None, metodo='HNSW', metrica='cosine', texto='BM25',
                   categoria='', min_price=None, max_price=None, lat=None, lon=None, solo_stock=False):
        inicio = time.perf_counter()
        estado = self.verificar()
        pesos = dict(PESOS if pesos is None else pesos)
        fusionar({}, pesos)  # Validar incluso si ninguna modalidad devuelve candidatos.
        if metodo not in ('HNSW', 'IVF', 'EXACT') or metrica not in ('cosine', 'euclidean', 'dot') or texto not in ('BM25', 'TF_IDF'):
            raise ValueError('Método o métrica no admitido')
        repo = Repositorio(self.conexion)
        productos = self.productos(repo)
        base = productos.get(pid)
        if base is None:
            raise LookupError('Producto inexistente')
        limites = min(len(productos), max(100, 10 * k))
        errores = {}
        listas = {m: [] for m in MODALIDADES}
        if self.conexion.catalog.existe_tabla('ecommerce_afinidades') and pesos['compras'] > 0:
            afines = repo.ejecutar(f'SELECT producto_destino, score, soporte FROM ecommerce_afinidades WHERE producto_origen = {int(pid)}')
            afines.sort(key=lambda r: (-r['score'], -r['soporte'], r['producto_destino']))
            listas['compras'] = [(r['producto_destino'], r['score']) for r in afines]
        contenido = repo.ejecutar(f'SELECT contenido FROM ecommerce_textos WHERE id = {int(pid)}')
        import re
        palabras = list(dict.fromkeys(re.findall(r'\w+', base['nombre'] + ' ' + (contenido[0]['contenido'] if contenido else ''))))[:40]
        misma_categoria = repo.ejecutar(f'SELECT id FROM ecommerce_productos WHERE categoria = {literal(base["categoria"])}')
        for fila in misma_categoria:
            p = productos[fila['id']]
            cercania = 1 / (1 + abs(p['precio_centavos'] - base['precio_centavos']) / max(base['precio_centavos'], 1))
            score = 2 * (p['subcategoria'] == base['subcategoria']) + (bool(p['marca']) and p['marca'] == base['marca']) + cercania
            listas['metadata'].append((p['id'], score))
        listas['metadata'].sort(key=lambda par: (-par[1], par[0]))
        while True:
            if pesos['visual'] > 0 and base['ruta'] and 'visual' not in errores:
                tabla = 'ecommerce_imagenes_ivf' if metodo == 'IVF' else 'ecommerce_imagenes_hnsw'
                try:
                    filas = repo.ejecutar(f'SELECT id, SIMILARITY_SCORE() AS score FROM {tabla} WHERE SIMILAR_TO({literal(base["ruta"])}, k={limites}) USING {metodo} WITH METRIC={metrica}')
                    listas['visual'] = [(r['id'], r['score']) for r in filas if r['score'] > 0]
                except (ValueError, OSError) as error:
                    errores['visual'] = str(error)
            if pesos['texto'] > 0 and palabras:
                filas = repo.ejecutar(f'SELECT id, SCORE() AS score FROM ecommerce_textos WHERE MATCH(contenido, {literal(" ".join(palabras))}) USING {texto} LIMIT {limites}')
                listas['texto'] = [(r['id'], r['score']) for r in filas]
            filtradas = {}
            for modalidad, candidatos in listas.items():
                filtradas[modalidad] = [(i, s) for i, s in candidatos if i in productos and i != pid
                                       and (not categoria or productos[i]['categoria'] == categoria)
                                       and (min_price is None or productos[i]['precio_centavos'] >= min_price)
                                       and (max_price is None or productos[i]['precio_centavos'] <= max_price)]
            fusion = fusionar(filtradas, pesos)
            if len(fusion) >= k or limites >= len(productos):
                break
            limites = min(len(productos), limites * 2)
        recomendaciones = [{**productos[r['id']], **r} for r in fusion[:k]]
        return {'producto_base': base, 'recomendaciones': recomendaciones,
                'modalidades': {m: ('error' if m in errores else 'desactivada' if pesos[m] == 0 else 'activa' if filtradas[m] else 'sin_datos') for m in MODALIDADES},
                'errores_modalidades': errores, 'trazas': repo.trazas, 'candidatos_por_busqueda': limites,
                'version_catalogo': estado['firma_catalogo'],
                'version_afinidades': repo.ejecutar('SELECT revision FROM ecommerce_estado WHERE id = 1')[0]['revision'] if self.conexion.catalog.existe_tabla('ecommerce_estado') else 0, 'tiempo_total_ms': round((time.perf_counter() - inicio) * 1000, 3)}
