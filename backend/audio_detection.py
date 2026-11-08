from dataclasses import replace
from functools import lru_cache
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deteccion.detector import BusquedaAudio, Detector, Parametros
from multimedia import bovw, config
from multimedia import colecciones_audio
from multimedia.colecciones_audio import normalizar_ruta, ruta_local
from multimedia.mfcc import cargar_audio


class DetectionRequest(BaseModel):
    path: str
    n_coleccion: int = Field(default=10000, gt=0)
    segmento_s: float = Field(default=5, ge=5, le=10)
    paso_s: float = Field(default=.5, ge=.1, le=1)
    k: int = Field(default=100, ge=1, le=200)
    umbral: float = Field(default=.65, ge=0, le=1)
    min_votos: int = Field(default=2, ge=2, le=20)
    metodo: str = 'EXACTO'
    representacion: str = 'hibrida'
    umbral_secuencia: float = Field(default=.60, ge=0, le=1)
    reducir_ruido: bool = True


def resolver_subida(root, ruta):
    uploads = (Path(root) / 'data' / 'uploads').resolve()
    candidato = (Path(root) / 'data' / ruta).resolve()
    if not candidato.is_relative_to(uploads) or not candidato.is_file():
        raise ValueError('seleccione un audio subido a data/uploads')
    if candidato.suffix.lower() not in config.EXTENSIONES_AUDIO:
        raise ValueError('el archivo debe ser un audio compatible')
    return candidato


def tabla_audio(n):
    return colecciones_audio.tabla(n)


def url_original(ruta, root):
    ruta = normalizar_ruta(ruta)
    if Path(ruta).is_absolute():
        try:
            ruta = Path(ruta).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            return None

    if not ruta.startswith(('bench/data/', 'data/')) or '..' in Path(ruta).parts:
        return None
    base = os.environ.get('MEDIA_BASE_URL', '').rstrip('/')
    return (base or '/api/media') + '/' + quote(ruta, safe='/')


def enriquecer(resultado, metadatos, root):
    for item in resultado['coincidencias'] + [c for s in resultado['segmentos']
                                              for c in s['coincidencias'] + s['candidatos']]:
        meta = metadatos.get(item['track_id'], {})
        item.update(titulo=meta.get('titulo') or 'Pista ' + item['track_id'],
                    artista=meta.get('artista') or 'Artista desconocido',
                    genero=meta.get('genero', ''),
                    audio_url=url_original(meta.get('ruta', ''), root))
        if meta.get('fuente'):
            item.update(fuente=meta['fuente'], id_origen=meta.get('id_origen', item['track_id']))
    return resultado


def leer_metadatos(engine, tabla, con_procedencia):
    columnas_origen = ', fuente, id_origen' if con_procedencia else ''
    res = engine.execute_query('SELECT track_id, segmento, titulo, artista, genero, ruta' + columnas_origen + ' FROM ' + tabla + ';')
    if res['status'] != 'success':
        raise ValueError(res.get('error') or 'No se pudieron leer los metadatos')
    metas, segmentos = {}, set()
    for fila in res['rows']:
        meta = dict(zip(res['columns'], fila))
        metas[str(meta['track_id'])] = meta
        segmentos.add((str(meta['track_id']), int(meta['segmento'])))
    return metas, segmentos


def crear_router(engine, root):
    router = APIRouter(prefix='/api/audio', tags=['Deteccion de audio'])
    catalog_lock = threading.RLock()
    busqueda_lock = threading.Lock()
    metadatos_lock = threading.Lock()

    def leer_tabla(tabla, con_procedencia):
        return leer_metadatos(engine, tabla, con_procedencia)

    @lru_cache(maxsize=2)
    def metadatos_guardados(tabla, con_procedencia, firma, revision, refrescar=False):
        data_dir = getattr(engine, 'data_dir', None)
        ruta = Path(data_dir) / 'cache_audio' / (tabla + '.json') if data_dir is not None else None
        identidad = {'version': 1, 'tabla': tabla, 'con_procedencia': con_procedencia,
                     'firma': [list(f) for f in firma]}
        if ruta is not None and revision == 0 and not refrescar:
            try:
                snapshot = json.loads(ruta.read_text(encoding='utf-8'))
                if isinstance(snapshot, dict) and snapshot.get('identidad') == identidad:
                    metas = snapshot['metadatos']
                    segmentos = {(str(tid), int(seg)) for tid, seg in snapshot['segmentos']}
                    requeridos = {'track_id', 'segmento', 'titulo', 'artista', 'genero', 'ruta'}
                    if con_procedencia:
                        requeridos.update(('fuente', 'id_origen'))
                    if not isinstance(metas, dict) or not all(isinstance(m, dict) and requeridos <= m.keys() for m in metas.values()):
                        raise ValueError('Snapshot de metadatos incompleto')
                    if set(metas) != {tid for tid, _ in segmentos}:
                        raise ValueError('Snapshot de metadatos inconsistente')
                    return metas, segmentos, 'disco'
            except (OSError, ValueError, TypeError, KeyError):
                pass
        metas, segmentos = leer_tabla(tabla, con_procedencia)
        if ruta is not None and revision == 0:
            temporal = None
            try:
                actual = tuple((str(p), s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino)
                               for p, *_ in firma for s in [Path(p).stat()])
                if actual == firma:
                    ruta.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=ruta.parent, suffix='.tmp', delete=False) as f:
                        temporal = Path(f.name)
                        json.dump({'identidad': identidad, 'metadatos': metas,
                                   'segmentos': sorted(segmentos)}, f, ensure_ascii=False, separators=(',', ':'))
                    os.replace(temporal, ruta)
            except OSError:
                pass
            finally:
                if temporal is not None:
                    try:
                        temporal.unlink(missing_ok=True)
                    except OSError:
                        pass
        return metas, segmentos, 'sql'

    def obtener_metadatos(tabla, con_procedencia, refrescar=False):
        try:
            archivos = engine.catalog.get_table(tabla).storage.file_paths()
            firma = tuple((str(p), s.st_mtime_ns, s.st_ctime_ns, s.st_size, s.st_ino)
                          for p in archivos for s in [Path(p).stat()])
        except (AttributeError, FileNotFoundError):
            return (*leer_tabla(tabla, con_procedencia), False, 'sql')
        with metadatos_lock:
            if refrescar:
                metadatos_guardados.cache_clear()
            hits = metadatos_guardados.cache_info().hits
            metas, segmentos, origen = metadatos_guardados(tabla, con_procedencia, firma,
                                                         getattr(engine, 'data_revision', 0), refrescar)
            if metadatos_guardados.cache_info().hits > hits:
                origen = 'memoria'
            return metas, segmentos, origen != 'sql', origen

    def preparar(n, metodo, representacion):
        vectores, ids = bovw.cargar_coleccion('audio', n)
        return BusquedaAudio(vectores, ids, metodo, representacion)

    @lru_cache(maxsize=1)
    def busqueda_guardada(n, metodo, representacion, firma):
        return preparar(n, metodo, representacion)

    def obtener_busqueda(n, params):
        carpeta = config.directorio_coleccion('audio', n)
        try:
            archivos = (carpeta / nombre for nombre in ('coleccion.json', 'vectores.npy', 'ids.npy'))
            firma = tuple((info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino) for info in map(Path.stat, archivos))
        except FileNotFoundError:
            return preparar(n, params.metodo, params.representacion)
        with busqueda_lock:
            return busqueda_guardada(n, params.metodo, params.representacion, firma)

    def precalentar():
        try:
            import scipy.signal
            import librosa
            from deteccion import chroma
            n = bovw.n_coleccion_vigente('audio')
            bovw._extractor('audio', n)
            obtener_busqueda(n, Parametros())
        except Exception:
            pass

    router.precalentar = precalentar

    @router.get('/collections')
    def colecciones(incluir_auxiliares: bool = False):
        if getattr(engine, 'data_dir', None) is not None and getattr(engine, 'pool', None) is not None:
            from query import catalog_store
            with catalog_lock:
                catalog_store.cargar(engine.catalog, engine.pool, engine.data_dir)
        carpeta = config.directorio_colecciones('audio')
        salida = []
        for ruta in carpeta.glob('*/coleccion.json'):
            if not ruta.parent.name.isdigit():
                continue
            n = int(ruta.parent.name)
            info = json.loads(ruta.read_text(encoding='utf-8'))
            tabla = colecciones_audio.tabla(n, info)
            if engine.catalog.existe_tabla(tabla):
                salida.append(colecciones_audio.describir(n, info))
        if not incluir_auxiliares:
            fuentes = [c for c in salida if c['completa'] and not c['unificada']]
            salida = fuentes or [c for c in salida if c['completa']] or salida
        return {'colecciones': sorted(salida, key=lambda c: c['n'])}

    @router.post('/detect')
    def detectar(req: DetectionRequest):
        inicio_total = time.perf_counter()
        try:
            ruta = resolver_subida(root, req.path)
            params = replace(Parametros(), **req.model_dump(exclude={'path', 'n_coleccion'}))
            params.validar()
            tabla = tabla_audio(req.n_coleccion)
            if not engine.catalog.existe_tabla(tabla):
                raise ValueError('Falta la tabla ' + tabla + '; importe la coleccion de audio primero')
            extractor = bovw._extractor('audio', req.n_coleccion)
            busqueda = obtener_busqueda(req.n_coleccion, params)
            info = colecciones_audio.informacion(req.n_coleccion)
            inicio_meta = time.perf_counter()
            metas, segmentos_tabla, cache_meta, origen_meta = obtener_metadatos(tabla, bool(info.get('con_procedencia')))
            tiempo_meta = (time.perf_counter() - inicio_meta) * 1000
            faltantes = set(busqueda.ids) - segmentos_tabla
            if faltantes and cache_meta:
                metas, segmentos_tabla, cache_meta, origen_meta = obtener_metadatos(
                    tabla, bool(info.get('con_procedencia')), refrescar=True)
                faltantes = set(busqueda.ids) - segmentos_tabla
                tiempo_meta = (time.perf_counter() - inicio_meta) * 1000
            if faltantes:
                raise ValueError(f'Faltan {len(faltantes)} segmentos de la biblioteca en la tabla {tabla}. '
                                 'Actualice la biblioteca y compruebe que usa la colección correspondiente.')
            y = cargar_audio(ruta, int(extractor.meta['sr']))
            def original(pid):
                return ruta_local(metas[pid]['ruta'], root)
            detector = Detector(None, None, extractor, params, resolver_original=original, busqueda=busqueda)
            resultado = enriquecer(detector.detectar(y), metas, root)
            resultado['metricas'].update(metadata_ms=round(tiempo_meta, 2), metadata_cache=cache_meta,
                                          metadata_origen=origen_meta,
                                          total_ms=round((time.perf_counter() - inicio_total) * 1000, 2))
            resultado.update(n_coleccion=req.n_coleccion, tabla=tabla, audio_url='/api/media/' + quote(req.path, safe='/'))
            return resultado
        except FileNotFoundError as ex:
            raise HTTPException(status_code=409, detail='Modelo no disponible: ' + str(ex)) from ex
        except (ValueError, OSError, RuntimeError) as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex

    return router
