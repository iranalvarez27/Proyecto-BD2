from dataclasses import asdict, dataclass
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import os
import tempfile
import time

import faiss
import numpy as np

from index.vector.exacto import knn_exacto_lote
from index.vector.faiss_base import IndiceFaiss
from index.vector.hnsw import HNSW
from index.vector.ivf import IVF


@dataclass(frozen=True)
class Parametros:
    segmento_s: float = 5.0
    paso_s: float = 0.5
    k: int = 100
    umbral: float = 0.65
    min_votos: int = 2
    tolerancia_s: float = 1.0
    velocidades: tuple = (0.95, 1.0, 1.05)
    representacion: str = 'hibrida'
    metodo: str = 'EXACTO'
    umbral_secuencia: float = 0.60
    reducir_ruido: bool = True

    def validar(self):
        if not 5 <= self.segmento_s <= 10:
            raise ValueError('segmento_s debe estar entre 5 y 10 segundos')
        if not 0.1 <= self.paso_s <= 1:
            raise ValueError('paso_s debe estar entre 0.1 y 1 segundo')
        if not 1 <= self.k <= 200:
            raise ValueError('k debe estar entre 1 y 200')
        if not 0 <= self.umbral <= 1 or not math.isfinite(self.umbral):
            raise ValueError('umbral debe estar entre 0 y 1')
        if not 2 <= self.min_votos <= 20:
            raise ValueError('min_votos debe estar entre 2 y 20')
        if not 0 < self.tolerancia_s <= 3:
            raise ValueError('tolerancia_s debe ser positiva y no mayor de 3')
        if not self.velocidades or any(not 0.8 <= v <= 1.2 for v in self.velocidades):
            raise ValueError('velocidades debe contener factores entre 0.8 y 1.2')
        if self.representacion not in ('boaw', 'raiz', 'hibrida'):
            raise ValueError('representacion debe ser boaw, raiz o hibrida')
        if not 0 <= self.umbral_secuencia <= 1:
            raise ValueError('umbral_secuencia debe estar entre 0 y 1')
        if self.metodo not in ('EXACTO', 'HNSW', 'IVF'):
            raise ValueError('metodo debe ser EXACTO, HNSW o IVF')


def representar(x, modo):
    x = np.asarray(x, dtype=np.float32)
    if not np.isfinite(x).all() or (x < 0).any():
        raise ValueError('los vectores BoAW deben ser finitos y no negativos')
    return np.sqrt(x) if modo == 'raiz' else x


def buscar_exacto(consultas, vectores, k, bloque=4096):

    q = np.asarray(consultas, dtype=np.float32)
    k = min(k, len(vectores))
    posiciones = np.empty((len(q), 0), np.int64)
    distancias = np.empty((len(q), 0), np.float32)
    for inicio in range(0, len(vectores), bloque):
        p, d = knn_exacto_lote(q, vectores[inicio:inicio + bloque], k, 'cosine')
        p = np.concatenate((posiciones, p + inicio), axis=1)
        d = np.concatenate((distancias, d), axis=1)
        orden = np.argsort(d, axis=1, kind='stable')[:, :k]
        posiciones = np.take_along_axis(p, orden, axis=1)
        distancias = np.take_along_axis(d, orden, axis=1)
    return posiciones, distancias


def alinear(hits, params, max_alineaciones=1):


    candidatos = []
    por_pista = {}
    for h in hits:
        if h['similitud'] >= params.umbral:
            por_pista.setdefault(h['track_id'], []).append(h)
    for pista, vecinos in por_pista.items():
        alineaciones = []
        for velocidad in params.velocidades:
            orden = sorted(vecinos, key=lambda h: h['original_s'] - velocidad * h['consulta_s'])
            offsets = [h['original_s'] - velocidad * h['consulta_s'] for h in orden]
            derecha = 0
            for izquierda, offset in enumerate(offsets):
                while derecha < len(orden) and offsets[derecha] - offset <= 2 * params.tolerancia_s:
                    derecha += 1
                unicos = {}
                for h in orden[izquierda:derecha]:
                    t = h['consulta_s']
                    if t not in unicos or h['similitud'] > unicos[t]['similitud']:
                        unicos[t] = h
                votos = list(unicos.values())
                if len(votos) < params.min_votos:
                    continue

                if max(unicos) - min(unicos) < 1.0:
                    continue
                score = float(np.mean([h['similitud'] for h in votos]))
                clave = (len(votos), score, -abs(1 - velocidad))
                desplazamiento = float(np.median([
                    h['original_s'] - velocidad * h['consulta_s'] for h in votos
                ]))
                alineaciones.append((clave, {
                    'track_id': pista, 'similitud': score,
                    'porcentaje_similitud': round(100 * score, 2),
                    'votos': len(votos), 'instantes_voto': sorted(unicos), 'velocidad': velocidad,
                    'desplazamiento_s': desplazamiento,
                    'evidencia_inicio_s': min(unicos),
                    'evidencia_fin_s': max(unicos),
                }))
        elegidas = []
        for _, candidato in sorted(alineaciones, key=lambda par: par[0], reverse=True):
            if all(abs(candidato['desplazamiento_s'] - c['desplazamiento_s']) > 2 * params.tolerancia_s for c in elegidas):
                elegidas.append(candidato)
            if len(elegidas) >= max_alineaciones:
                break
        candidatos.extend(elegidas)
    return sorted(candidatos, key=lambda c: (-c['votos'], -c['similitud'], c['track_id']))


def fusionar(segmentos, duracion_ventana, duracion, params):

    eventos = []
    for segmento in segmentos:
        for candidato in segmento['coincidencias']:
            inicio = max(segmento['inicio_s'], candidato['evidencia_inicio_s'])
            fin = min(duracion, segmento['fin_s'], candidato['evidencia_fin_s'] + duracion_ventana)
            velocidad = candidato['velocidad']
            offset = candidato['desplazamiento_s']
            previo = next((e for e in reversed(eventos)
                           if e['track_id'] == candidato['track_id']
                           and inicio <= e['fin_s'] + params.paso_s
                           and abs(e['velocidad'] - velocidad) <= 0.051
                           and abs(e['desplazamiento_s'] - offset) <= 2 * params.tolerancia_s), None)
            if previo is not None:
                instantes = sorted(set(previo['instantes_voto']) | set(candidato['instantes_voto']))
                nuevos = len(instantes) - previo['votos']
                peso = len(instantes)
                previo['similitud'] = (previo['similitud'] * previo['votos'] + candidato['similitud'] * nuevos) / peso
                previo['instantes_voto'] = instantes
                previo['porcentaje_similitud'] = round(previo['similitud'] * 100, 2)
                previo['votos'] = peso
                previo['fin_s'] = max(previo['fin_s'], fin)
                previo['original_fin_s'] = max(previo['original_fin_s'], offset + velocidad * fin)
            else:
                eventos.append({**candidato, 'inicio_s': inicio, 'fin_s': fin,
                                'original_inicio_s': max(0., offset + velocidad * inicio),
                                'original_fin_s': max(0., offset + velocidad * fin)})
    return sorted(eventos, key=lambda e: (e['inicio_s'], e['track_id']))


class _IndicePlanoCoseno(IndiceFaiss):
    def _nuevo(self, dim, n):
        return faiss.IndexFlatIP(dim)

    def _parametros(self):
        return None


class BusquedaAudio:


    def __init__(self, vectores, ids, metodo, representacion):
        self.ids = tuple((str(o[0]), int(o[1])) for o in ids)
        self.metodo = metodo
        self.representacion = representacion
        base = representar(vectores, representacion)
        if base.ndim != 2 or not len(base) or len(self.ids) != len(base):
            raise ValueError('coleccion de audio vacia o inconsistente')
        self.indice = self._crear_indice(base)
        self.indice_raiz = (self._crear_indice(representar(base, 'raiz'))
                            if representacion == 'hibrida' else None)

    def _crear_indice(self, vectores):
        if self.metodo == 'EXACTO':
            indice = _IndicePlanoCoseno('cosine')
        elif self.metodo == 'HNSW':
            indice = HNSW('cosine', M=32, efConstruction=300)
        else:
            nlist = max(1, round(math.sqrt(len(self.ids))))
            indice = IVF('cosine', nlist=nlist, nprobe=min(nlist, max(16, math.ceil(nlist * .5))))
        indice.build(vectores)
        return indice

    def buscar(self, consultas, k):
        k = min(k, len(self.ids))
        opciones = {'efSearch': max(256, k * 4)} if self.metodo == 'HNSW' else {}
        posiciones, distancias = self.indice.search_lote(consultas, k, **opciones)
        if self.indice_raiz is not None:
            pr, dr = self.indice_raiz.search_lote(representar(consultas, 'raiz'), k, **opciones)
            posiciones = np.concatenate((posiciones, pr), axis=1)
            distancias = np.concatenate((distancias, dr), axis=1)
        return posiciones, distancias


def _extraer_original(ruta, extractor):
    from multimedia.mfcc import cargar_audio

    senal = cargar_audio(ruta, int(extractor.meta['sr']))
    return extractor._descriptores_audio(senal)


@lru_cache(maxsize=512)
def _mfcc_original(ruta, extractor, firma):
    modelo = getattr(extractor, 'directorio', None)
    if modelo is None:
        return _extraer_original(ruta, extractor)
    modelo = Path(modelo)
    ruta_cache = None
    try:
        parametros = {k: extractor.meta.get(k) for k in
                      ('sr', 'n_fft', 'hop', 'n_mfcc', 'dim', 'huella_codebook')}
        archivos = [modelo / 'meta.json', modelo / 'estandarizacion.npz']
        firma_modelo = [(p.name, s.st_mtime_ns, s.st_ctime_ns, s.st_size)
                        for p in archivos if p.exists() for s in [p.stat()]]
        identidad = json.dumps([1, str(Path(ruta).resolve()), firma, parametros, firma_modelo],
                              sort_keys=True, separators=(',', ':'))
        clave = hashlib.sha256(identidad.encode('utf-8')).hexdigest()
        ruta_cache = modelo / 'secuencias' / (clave + '.npy')
        datos = np.load(ruta_cache, allow_pickle=False)
        dim = int(extractor.meta.get('dim', int(extractor.meta.get('n_mfcc', 20)) - 1))
        if datos.ndim == 2 and datos.shape[1] == dim and datos.dtype == np.float32 and np.isfinite(datos).all():
            return datos
    except (OSError, ValueError, TypeError):
        pass
    datos = _extraer_original(ruta, extractor)
    if ruta_cache is not None:
        temporal = None
        try:
            ruta_cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile('wb', dir=ruta_cache.parent, suffix='.tmp', delete=False) as f:
                temporal = Path(f.name)
                np.save(f, datos, allow_pickle=False)
            os.replace(temporal, ruta_cache)
        except OSError:
            pass
        finally:
            if temporal is not None:
                try:
                    temporal.unlink(missing_ok=True)
                except OSError:
                    pass
    return datos


_PREFETCH_ORIGINALES = ThreadPoolExecutor(max_workers=4)


class Detector:
    def __init__(self, vectores, ids, extractor, params=None, resolver_original=None, *, busqueda=None):
        self.params = params or Parametros()
        self.params.validar()
        self.extractor = extractor
        self.resolver_original = resolver_original
        self._originales = OrderedDict()
        self._secuencias_preparadas = OrderedDict()
        self._fft_consultas = OrderedDict()
        self.busqueda = busqueda or BusquedaAudio(
            vectores, ids, self.params.metodo, self.params.representacion)
        self.ids = self.busqueda.ids
        self.sr = int(extractor.meta['sr'])
        self.seg_s = float(extractor.meta['seg_s'])
        if self.seg_s > self.params.segmento_s:
            raise ValueError('el segmento de analisis debe ser al menos tan largo como el indexado')

    def _leer_original(self, pista):
        ruta = Path(self.resolver_original(pista))
        try:
            info = ruta.stat()
        except FileNotFoundError:
            return _extraer_original(ruta, self.extractor)
        firma = (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)
        return _mfcc_original(ruta, self.extractor, firma)

    def _precargar_originales(self, candidatos):
        faltantes = list(dict.fromkeys(c['track_id'] for c in candidatos
                                       if c['track_id'] not in self._originales))
        if not faltantes:
            return
        resultados = _PREFETCH_ORIGINALES.map(self._leer_original, faltantes)
        for pista, descriptores in zip(faltantes, resultados):
            self._originales[pista] = descriptores
            if len(self._originales) > 128:
                self._originales.popitem(last=False)

    def verificar_secuencia(self, candidato, desc_consulta, inicio, fin):


        pista = candidato['track_id']
        if pista not in self._originales:
            descriptores = self._leer_original(pista)
            self._originales[pista] = descriptores
            if len(self._originales) > 128:
                self._originales.popitem(last=False)
        self._originales.move_to_end(pista)
        fuente = self._originales[pista]
        fps = self.sr / int(self.extractor.meta['hop'])
        a, b = int(np.ceil(inicio * fps)), min(len(desc_consulta), int(fin * fps))
        q = desc_consulta[a:b].astype(np.float64)
        if len(q) < fps:
            return None
        from scipy.fft import irfft, next_fast_len, rfft
        mejor = None
        cantidad = len(q)
        suma_q = q.sum(axis=0)
        norma_q = float(np.sum(q*q))
        norma_q_centrada = max(0., norma_q - float(suma_q @ suma_q) / cantidad)
        contenido_q = (q.shape, q.tobytes())


        for velocidad in self.params.velocidades:
            clave = (pista, id(fuente), velocidad)
            preparada = self._secuencias_preparadas.pop(clave, None)
            if preparada is None:
                if velocidad == 1:
                    fuente_muestreada = fuente[:-1].astype(np.float64)
                else:
                    indices = np.arange(0, len(fuente) - 1, velocidad)
                    lo = indices.astype(np.int64)
                    peso = (indices - lo)[:, None]
                    fuente_muestreada = fuente[lo] * (1-peso) + fuente[lo+1] * peso
                acumulado = np.vstack((np.zeros((1, q.shape[1])), np.cumsum(fuente_muestreada, axis=0)))
                potencias = np.r_[0., np.cumsum(np.sum(fuente_muestreada**2, axis=1))]
                preparada = (fuente_muestreada, acumulado, potencias, OrderedDict(), OrderedDict())
            self._secuencias_preparadas[clave] = preparada


            if len(self._secuencias_preparadas) > 8:
                self._secuencias_preparadas.popitem(last=False)
            fuente_muestreada, acumulado, potencias, fft_fuentes, estadisticas = preparada
            if len(fuente_muestreada) < cantidad:
                continue
            nfft = next_fast_len(len(fuente_muestreada) + cantidad - 1, real=True)
            fft_fuente = fft_fuentes.pop(nfft, None)
            if fft_fuente is None:
                fft_fuente = rfft(fuente_muestreada, nfft, axis=0)
            fft_fuentes[nfft] = fft_fuente
            if len(fft_fuentes) > 2:
                fft_fuentes.popitem(last=False)
            clave_q = (*contenido_q, nfft)
            fft_q = self._fft_consultas.pop(clave_q, None)
            if fft_q is None:
                fft_q = rfft(q[::-1], nfft, axis=0)
            self._fft_consultas[clave_q] = fft_q
            if len(self._fft_consultas) > 8:
                self._fft_consultas.popitem(last=False)
            espectro = (fft_fuente * fft_q).sum(axis=1)
            producto = irfft(espectro, nfft)[cantidad - 1:len(fuente_muestreada)]
            resumen = estadisticas.pop(cantidad, None)
            if resumen is None:
                sumas = acumulado[cantidad:] - acumulado[:-cantidad]
                norma_x = np.maximum(0., potencias[cantidad:] - potencias[:-cantidad])
                norma_x_centrada = np.maximum(0., norma_x - np.sum(sumas**2, axis=1) / cantidad)
                resumen = (sumas, norma_x, norma_x_centrada)
            estadisticas[cantidad] = resumen
            if len(estadisticas) > 2:
                estadisticas.popitem(last=False)
            sumas, norma_x, norma_x_centrada = resumen
            denominador = np.sqrt(norma_q * norma_x)
            absoluto = np.divide(producto, denominador, out=np.zeros_like(producto), where=denominador > 1e-12)
            centrado = producto - sumas @ suma_q / cantidad
            denominador_centrado = np.sqrt(norma_q_centrada * norma_x_centrada)
            dinamico = np.divide(centrado, denominador_centrado, out=np.zeros_like(producto), where=denominador_centrado > 1e-12)
            scores = .5 * np.maximum(0., absoluto) + .5 * np.maximum(0., dinamico)
            ix = int(np.argmax(scores))
            if mejor is None or scores[ix] > mejor[0]:
                offset = velocidad * (ix - a) / fps
                mejor = (float(np.clip(scores[ix], 0, 1)), float(offset), velocidad)
        if mejor is None or mejor[0] < self.params.umbral_secuencia:
            return None
        score, offset, velocidad = mejor
        return {**candidato, 'similitud_boaw': candidato['similitud'],
                'similitud_secuencia': score,
                'similitud': score, 'porcentaje_similitud': round(100 * score, 2),
                'desplazamiento_s': float(offset), 'velocidad': velocidad}

    def _verificar_segmentos(self, segmentos, desc_consultas):
        pendientes = {}
        verificadas = [{} for _ in segmentos]
        for numero, segmento in enumerate(segmentos):
            for posicion, candidato in enumerate(segmento['coincidencias']):
                pendientes.setdefault(candidato['track_id'], []).append((numero, posicion, candidato))
        pistas = list(pendientes)
        for primero in range(0, len(pistas), 8):
            lote = pistas[primero:primero + 8]
            self._precargar_originales([{'track_id': pista} for pista in lote])
            for pista in lote:
                for numero, posicion, candidato in pendientes[pista]:
                    segmento = segmentos[numero]
                    opciones = [v for desc in desc_consultas
                                if (v := self.verificar_secuencia(candidato, desc, segmento['inicio_s'],
                                                                  segmento['fin_s'])) is not None]
                    if opciones:
                        verificadas[numero][posicion] = max(opciones, key=lambda v: v['similitud'])
        for numero, segmento in enumerate(segmentos):
            por_pista = {}
            for posicion in sorted(verificadas[numero]):
                candidato = verificadas[numero][posicion]
                pista = candidato['track_id']
                if pista not in por_pista or candidato['similitud'] > por_pista[pista]['similitud']:
                    por_pista[pista] = candidato
            segmento['coincidencias'] = sorted(por_pista.values(), key=lambda c: -c['similitud'])

    def detectar(self, y):
        inicio = time.perf_counter()
        y = np.asarray(y, dtype=np.float32)
        if y.ndim != 1 or not np.isfinite(y).all():
            raise ValueError('se requiere audio mono con muestras finitas')
        duracion = len(y) / self.sr
        if duracion < 5:
            raise ValueError('la consulta debe contener al menos 5 segundos de audio')
        if duracion > 600:
            raise ValueError('la consulta no debe superar 10 minutos')

        vistas = [y]
        if self.params.reducir_ruido and self.extractor.meta.get('n_fft'):
            from multimedia.mfcc import reducir_ruido_estacionario
            vistas.append(reducir_ruido_estacionario(
                y, int(self.extractor.meta['n_fft']), int(self.extractor.meta['hop'])))
        extracciones = [self.extractor.vectores_senal(vista, self.params.paso_s) for vista in vistas]
        tiempos = np.concatenate([t for t, _ in extracciones])
        Q = representar(np.concatenate([q for _, q in extracciones]), self.params.representacion)
        hits = []
        ventana = int(self.seg_s * self.sr)
        for comienzo in range(0, len(Q), 32):
            consultas = Q[comienzo:comienzo + 32]
            instantes = tiempos[comienzo:comienzo + len(consultas)]

            activos = []
            for j, (t, consulta) in enumerate(zip(instantes, consultas)):
                muestra = int(round(float(t) * self.sr))
                if np.linalg.norm(consulta) > 0 and np.sqrt(np.mean(y[muestra:muestra + ventana] ** 2)) >= 1e-4:
                    activos.append(j)
            if not activos:
                continue
            posiciones, distancias = self.busqueda.buscar(consultas[activos], self.params.k)
            similitudes = np.clip(1.0 - distancias.astype(np.float64), 0.0, 1.0)
            for j, p, d, scores in zip(activos, posiciones, distancias, similitudes):
                t = float(instantes[j])
                validos = (p >= 0) & np.isfinite(d)
                for fila, similitud in zip(p[validos].tolist(), scores[validos].tolist()):
                    pista, segmento = self.ids[fila]
                    hits.append({'track_id': pista, 'consulta_s': t,
                                 'original_s': segmento * self.seg_s, 'similitud': similitud})

        inicios = list(np.arange(0, max(0., duracion - self.params.segmento_s), self.params.segmento_s))
        ultimo = max(0., duracion - self.params.segmento_s)


        if not (inicios and ultimo - inicios[-1] < self.params.paso_s
                and duracion - inicios[-1] <= 10):
            inicios.append(ultimo)
        segmentos = []
        desc_consultas = [self.extractor._descriptores_audio(vista) for vista in vistas] if self.resolver_original else []
        for numero, t in enumerate(inicios):
            fin = duracion if numero == len(inicios) - 1 else min(duracion, t + self.params.segmento_s)
            locales = [h for h in hits if t <= h['consulta_s'] and h['consulta_s'] + self.seg_s <= fin + 1e-6]
            coincidencias = alinear(locales, self.params, max_alineaciones=1)
            mejores = {}
            for h in locales:
                pista = h['track_id']
                mejores[pista] = max(mejores.get(pista, 0.), h['similitud'])
            candidatos = [{'track_id': p, 'similitud': s, 'porcentaje_similitud': round(100*s, 2)}
                          for p, s in sorted(mejores.items(), key=lambda par: -par[1])[:self.params.k]]
            segmentos.append({'inicio_s': float(t), 'fin_s': float(fin),
                              'coincidencias': coincidencias, 'candidatos': candidatos})
        if self.resolver_original:
            self._verificar_segmentos(segmentos, desc_consultas)
        eventos = fusionar(segmentos, self.seg_s, duracion, self.params)
        tiempo_chroma = 0.
        if self.resolver_original and duracion >= 10:
            from deteccion.chroma import verificar_tonal
            from multimedia import config
            inicio_chroma = time.perf_counter()
            carpeta = Path(getattr(self.extractor, 'directorio', config.directorio_modelo('audio'))) / 'cromas'
            tonales = verificar_tonal(y, self.sr, hits, self.params, self.resolver_original, carpeta, eventos)
            eventos = sorted(eventos + tonales, key=lambda e: (e['inicio_s'], e['track_id']))
            for segmento in segmentos:
                for evento in tonales:
                    if evento['inicio_s'] < segmento['fin_s'] and evento['fin_s'] > segmento['inicio_s']:
                        segmento['coincidencias'].append(evento.copy())
            tiempo_chroma = (time.perf_counter() - inicio_chroma) * 1000
        return {
            'duracion_s': duracion, 'segmentos': segmentos, 'coincidencias': eventos,
            'posible_coincidencia': bool(eventos),
            'conclusion': ('Se detectaron posibles coincidencias de audio.' if eventos else
                           'No se detectaron coincidencias con los parametros actuales.'),
            'aviso': 'La similitud es orientativa y no demuestra una infraccion. La verificacion musical puede omitir versiones con arreglos muy distintos; sus posiciones son aproximadas.',
            'parametros': asdict(self.params),
            'metricas': {'ventanas': len(Q), 'vectores_base': len(self.ids), 'chroma_ms': round(tiempo_chroma, 2),
                         'tiempo_ms': round((time.perf_counter() - inicio) * 1000, 2)},
        }
