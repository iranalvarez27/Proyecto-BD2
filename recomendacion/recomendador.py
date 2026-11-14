"""Consultas de contenido y catálogo ejecutadas mediante el motor SQL."""
from collections import OrderedDict
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import quote
import uuid

from recomendacion.fusion import MODALIDADES, combinar, fusionar
from recomendacion import semantico, visual
from recomendacion.indices import TABLA_SEMANTICA
from recomendacion.preparar import manifiesto
from recomendacion.repositorio import Repositorio, literal
from recomendacion.metadata import gower, rango_log_precio
from recomendacion.texto import terminos_relevantes

PESOS = {'visual': .25, 'texto': .25, 'metadata': .25, 'compras': .25}
PESOS_BUSQUEDA = {'bm25': .4, 'semantico': .4, 'popularidad': .2}
# senal de texto del recomendador: More Like This (TF-IDF) y vecinos MiniLM, por partes iguales
PESOS_TEXTO = {'lexico': .5, 'semantico': .5}


class Servicio:
    def __init__(self, conexion):
        self.conexion = conexion
        self.lock = threading.RLock()
        self.busquedas = OrderedDict()

    def estado(self):
        meta = manifiesto(self.conexion.data_dir) or {}
        indices = {}
        for tabla in self.conexion.catalog.listar_tablas():
            if tabla.startswith('ecommerce_'):
                info = self.conexion.catalog.get_table(tabla)
                indices[tabla] = {col: getattr(idx, 'metodo', tipo) for col, (idx, tipo) in info.indices.items()}
        return {**meta, 'productos': len(meta.get('asins', [])), 'indices': indices,
                'listo': bool(meta.get('catalogo_listo') and meta.get('indices_listos')),
                'datos_comerciales': 'Compras reales de Amazon Reviews 2023; inventario y sucursales simulados'}

    def verificar(self):
        estado = self.estado()
        if not estado['listo']:
            raise ValueError('Prepare el catálogo con python3 -m recomendacion.preparar y reinicie el backend')
        if estado.get('firma_visual') != visual.FIRMA or estado.get('firma_semantica') != semantico.FIRMA:
            raise ValueError('Cambió un modelo de embeddings. Reconstruya los índices de e-commerce antes de consultar.')
        visual.registrar()
        semantico.registrar()
        return estado

    def escala_compras(self, repo, estado):
        """Percentil 99 de los scores de compras: la escala global con que se normaliza esa senal."""
        if 'escala_compras' in estado:
            return estado['escala_compras']
        if getattr(self, '_escala', (None,))[0] != estado['firma_catalogo']:
            from recomendacion.afinidades import escala_global
            scores = [r['score'] for r in repo.ejecutar('SELECT score FROM ecommerce_afinidades')]
            self._escala = (estado['firma_catalogo'], escala_global(scores))
        return self._escala[1]

    def buscar(self, repo, texto, pesos=None, k_lexico=500, k_semantico=300):
        # mas alla de los primeros cientos, min-max deja el score casi en 0: no llegan arriba
        """Busqueda hibrida: BM25 y vecinos MiniLM sobre el mismo contenido, mas la popularidad
        (log de compradores reales) para desempatar entre lo que el texto encontro."""
        pesos = PESOS_BUSQUEDA if pesos is None else pesos
        listas = {}
        if pesos.get('bm25', 0) > 0:
            listas['bm25'] = [(r['id'], r['score']) for r in repo.ejecutar(
                f'SELECT id, SCORE() AS score FROM ecommerce_textos WHERE MATCH(contenido, {literal(texto)}) USING BM25 '
                f'LIMIT {int(k_lexico)}')]
        if pesos.get('semantico', 0) > 0:
            listas['semantico'] = [(r['id'], r['score']) for r in repo.ejecutar(
                f'SELECT id, SIMILARITY_SCORE() AS score FROM {TABLA_SEMANTICA} '
                f'WHERE SIMILAR_TO({literal(texto)}, k={int(k_semantico)}) USING HNSW WITH METRIC=cosine')]
        candidatos = sorted({i for lista in listas.values() for i, _ in lista})
        if pesos.get('popularidad', 0) > 0 and candidatos:
            compradores = {r['id']: r['compradores'] for r in repo.ejecutar(
                'SELECT id, compradores FROM ecommerce_compradores WHERE id IN (' + ','.join(map(str, candidatos)) + ')')}
            listas['popularidad'] = [(i, math.log1p(compradores.get(i, 0))) for i in candidatos]
        return combinar(listas, pesos)

    def categorias(self, repo, firma):
        # son las del catalogo curado; contarlas con GROUP BY recorre la tabla entera
        from recomendacion.catalogo import CATEGORIAS
        return list(CATEGORIAS)

    def mas_vendidos(self, categoria='', limite=12):
        """Productos con mas compradores reales, en todo el catalogo o en una categoria."""
        self.verificar()
        repo = Repositorio(self.conexion)
        revision = repo.ejecutar('SELECT revision FROM ecommerce_estado WHERE id = 1')[0]['revision']
        clave = (categoria, revision)
        # el ranking solo cambia con una compra nueva (revision): se guarda hasta entonces
        if clave not in getattr(self, '_vendidos', {}):
            if categoria:
                ids = [r['id'] for r in repo.ejecutar(f'SELECT id FROM ecommerce_productos WHERE categoria = {literal(categoria)}')]
                filas = repo.ejecutar('SELECT id, compradores FROM ecommerce_compradores WHERE id IN ('
                                      + ','.join(str(i) for i in ids) + ')') if ids else []
            else:
                filas = repo.ejecutar('SELECT id, compradores FROM ecommerce_compradores')
            self._vendidos = {k: v for k, v in getattr(self, '_vendidos', {}).items() if k[1] == revision}
            self._vendidos[clave] = sorted(filas, key=lambda r: (-r['compradores'], r['id']))[:50]
        top = self._vendidos[clave][:limite]
        productos = self.productos(repo, [r['id'] for r in top])
        return {'productos': [{**productos[r['id']], 'compradores': r['compradores']} for r in top if r['id'] in productos],
                'trazas': repo.trazas}

    def rango_precio(self, repo, firma):
        """Rango de ln(precio) del catalogo para Gower; se calcula una vez por catalogo."""
        if getattr(self, '_rango', (None,))[0] != firma:
            extremos = [repo.ejecutar(f'SELECT precio_centavos FROM ecommerce_productos ORDER BY precio_centavos {orden} LIMIT 1')
                        for orden in ('ASC', 'DESC')]
            self._rango = (firma, rango_log_precio([fila[0] for fila in extremos]))
        return self._rango[1]

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
        categorias = self.categorias(repo, estado['firma_catalogo'])
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
                hallados = [{'id': i, 'relevancia': v} for i, v in self.buscar(repo, search)]
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
            # los ids del catalogo son consecutivos: sin filtros la pagina es un rango del B+ de id;
            # con filtros, el indice de categoria o de precio trae los ids y se ordenan aca
            # (ORDER BY id LIMIT haria un external sort de toda la tabla)
            filtros.append(f'id > {int(after_id)}')
            if len(filtros) == 1:
                filtros.append(f'id <= {int(after_id) + limit + 1}')
            ordenados = sorted(p['id'] for p in repo.ejecutar('SELECT id FROM ecommerce_productos WHERE ' + ' AND '.join(filtros)))
            ids = ordenados[:limit]
            productos = self.productos(repo, ids)
            filas = [productos[i] for i in ids]
            if len(ordenados) > limit:
                siguiente = str(ids[-1])
        return {'productos': filas, 'categorias': categorias,
                'next_cursor': siguiente, 'busqueda_acotada': truncada, 'trazas': repo.trazas}

    def recomendar(self, pid, k=10, pesos=None, metodo='HNSW', metrica='cosine', texto='TF_IDF',
                   categoria='', min_price=None, max_price=None, lat=None, lon=None, solo_stock=False):
        inicio = time.perf_counter()
        estado = self.verificar()
        pesos = dict(PESOS if pesos is None else pesos)
        fusionar({}, pesos)  # Validar incluso si ninguna modalidad devuelve candidatos.
        if metodo not in ('HNSW', 'IVF', 'EXACT') or metrica not in ('cosine', 'euclidean', 'dot') or texto not in ('BM25', 'TF_IDF'):
            raise ValueError('Método o métrica no admitido')
        repo = Repositorio(self.conexion)
        base = self.productos(repo, [pid]).get(pid)
        if base is None:
            raise LookupError('Producto inexistente')
        total = len(estado['asins'])
        disponibles = None
        if solo_stock:
            disponibles = {r['producto_id'] for r in repo.ejecutar('SELECT producto_id FROM ecommerce_inventario WHERE stock > 0')}
        limites = min(total, max(100, 10 * k))
        errores = {}
        listas = {m: [] for m in MODALIDADES}
        if self.conexion.catalog.existe_tabla('ecommerce_afinidades') and pesos['compras'] > 0:
            afines = repo.ejecutar(f'SELECT producto_destino, score, soporte FROM ecommerce_afinidades WHERE producto_origen = {int(pid)}')
            afines.sort(key=lambda r: (-r['score'], -r['soporte'], r['producto_destino']))
            listas['compras'] = [(r['producto_destino'], r['score']) for r in afines]
        contenido = repo.ejecutar(f'SELECT contenido FROM ecommerce_textos WHERE id = {int(pid)}')
        indice_texto = self.conexion.catalog.get_table('ecommerce_textos').indices['contenido'][0]
        texto_base = contenido[0]['contenido'] if contenido else base['nombre']
        palabras = terminos_relevantes(indice_texto, texto_base)
        misma_categoria = repo.ejecutar('SELECT id, subcategoria, marca, precio_centavos FROM ecommerce_productos '
                                        f'WHERE categoria = {literal(base["categoria"])}')
        rango = self.rango_precio(repo, estado['firma_catalogo'])
        listas['metadata'] = sorted(((p['id'], gower(base, p, rango)) for p in misma_categoria), key=lambda par: (-par[1], par[0]))
        # categoria y precio de cada candidato, para los filtros
        datos = {p['id']: {'categoria': base['categoria'], 'precio_centavos': p['precio_centavos']} for p in misma_categoria}
        while True:
            if pesos['visual'] > 0 and base['ruta'] and 'visual' not in errores:
                tabla = 'ecommerce_imagenes_ivf' if metodo == 'IVF' else 'ecommerce_imagenes_hnsw'
                try:
                    filas = repo.ejecutar(f'SELECT id, SIMILARITY_SCORE() AS score FROM {tabla} WHERE SIMILAR_TO({literal(base["ruta"])}, k={limites}) USING {metodo} WITH METRIC={metrica}')
                    listas['visual'] = [(r['id'], r['score']) for r in filas if r['score'] > 0]
                except (ValueError, OSError) as error:
                    errores['visual'] = str(error)
            if pesos['texto'] > 0:
                lexico = [(r['id'], r['score']) for r in repo.ejecutar(
                    f'SELECT id, SCORE() AS score FROM ecommerce_textos WHERE MATCH(contenido, {literal(" ".join(palabras))}) '
                    f'USING {texto} LIMIT {limites}')] if palabras else []
                vecinos = [(r['id'], r['score']) for r in repo.ejecutar(
                    f'SELECT id, SIMILARITY_SCORE() AS score FROM {TABLA_SEMANTICA} '
                    f'WHERE SIMILAR_TO({literal(texto_base)}, k={limites}) USING HNSW WITH METRIC=cosine')]
                listas['texto'] = combinar({'lexico': lexico, 'semantico': vecinos}, PESOS_TEXTO)
            faltan = {i for candidatos in listas.values() for i, _ in candidatos} - datos.keys()
            if faltan:
                for p in repo.ejecutar('SELECT id, categoria, precio_centavos FROM ecommerce_productos WHERE id IN ('
                                       + ','.join(str(int(i)) for i in sorted(faltan)) + ')'):
                    datos[p['id']] = p
            filtradas = {}
            for modalidad, candidatos in listas.items():
                filtradas[modalidad] = [(i, s) for i, s in candidatos if i in datos and i != pid
                                       and (disponibles is None or i in disponibles)
                                       and (not categoria or datos[i]['categoria'] == categoria)
                                       and (min_price is None or datos[i]['precio_centavos'] >= min_price)
                                       and (max_price is None or datos[i]['precio_centavos'] <= max_price)]
            fusion = fusionar(filtradas, pesos, {'compras': self.escala_compras(repo, estado)})
            if len(fusion) >= k or limites >= total:
                break
            limites = min(total, limites * 2)
        completos = self.productos(repo, [r['id'] for r in fusion[:k]])
        recomendaciones = [{**completos[r['id']], **r} for r in fusion[:k]]
        from recomendacion.disponibilidad import tiendas_con_stock
        for producto in [base, *recomendaciones]:
            producto['tiendas'] = tiendas_con_stock(repo, producto['id'], lat, lon) if self.conexion.catalog.existe_tabla('ecommerce_tiendas') else []
        return {'producto_base': base, 'recomendaciones': recomendaciones,
                'modalidades': {m: ('error' if m in errores else 'desactivada' if pesos[m] == 0 else 'activa' if filtradas[m] else 'sin_datos') for m in MODALIDADES},
                'errores_modalidades': errores, 'trazas': repo.trazas, 'candidatos_por_busqueda': limites,
                'version_catalogo': estado['firma_catalogo'],
                'version_afinidades': repo.ejecutar('SELECT revision FROM ecommerce_estado WHERE id = 1')[0]['revision'] if self.conexion.catalog.existe_tabla('ecommerce_estado') else 0, 'tiempo_total_ms': round((time.perf_counter() - inicio) * 1000, 3)}
