import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import threading
import time

import librosa
import numpy as np

SR = 22050
HOP = 1024
AGRUPAR = 2
PASO_S = AGRUPAR * HOP / SR
BINS_OCTAVA = 36
FMIN = 'C2'
OCTAVAS_CQT = 7
OCTAVAS_MELODIA = 4
NOTA_BAJA = 0 
ARMONICOS = 6
PICOS_REFERENCIA = 3
SIGMA_SEMITONOS = 0.5
SILENCIO_DB = -45.0

UMBRAL = 0.62
MARGEN = 0.02
DURACION_MIN_S = 8.0
DURACION_MAX_S = 120.0
VOZ_MINIMA = 0.3

PASOS = np.array([[1, 1], [1, 2], [2, 1]])
PESO_SALTO = 0.1
PESOS_PASOS = np.array([0.0, PESO_SALTO, PESO_SALTO])
COSTO_SILENCIO = 0.5

RAIZ = Path(__file__).resolve().parents[1]
CARPETA_AUDIO = RAIZ / 'bench' / 'data' / 'musica_propia'

AVISO = ('Reconoce solo las canciones del repertorio. Compara la melodía, no la voz: cantar en otro tono o más '
         'lento está permitido; desafinar mucho baja el puntaje. La similitud es orientativa.')

CANCIONES_DEMO = (
    'pe9a7a64f08366cefc94d9',
    'pe28b21d1af2bdcfc1a921',
    'pef08ddb67673999b6032d',
    'pe533ae01b0604519abb0a',
    'pead580591b6eddd42a3b6',
    'pe37f88988615cd0560305',
    'pec646fd76f3dfc5d88ebf',
    'ped76401421e3cf1832820',
    'pe7d714f90c4491eed4761',
    'pec5a68e448aae84edf6f8',
    'pe4157e2dfc863b4770742',
    'pedcdf5f470e06060e65aa',
    'pe972b71d09fb09f5cbf80',
    'pe29d813d4fe7200872c1a',
    'pe3a942bcfe01882b7f616',
    'pe98009bf1050a2411978a',
    'pe258bf3f56704b25367fa',
    'peb4319a1a413b18871898',
    'pe551e72fc9600fdfb2596',
    'pe59f1560018828d3aef33',
    'pea71ff7e9121028f1178c',
    'pe5086fe0c56542c131ee0',
    'pea460d7ca18e6b153cc99',
    'pe2a8f6e769984b98e6aa1',
)

CANCIONES_AMPLIADAS = (
    'pe0e13cad8c4178e1c80b6',
    'pe17f730c02b9613ad2cbb',
    'pe010720b8ce2b09adfef4',
    'pe0e6752331d1859cd465f',
    'pe12436d34eab113b51160',  
    'pe02235ce9569adbeb6310',
    'pe1c2f074abbed52333028',
    'pe752f66ea170ac4ddbf91',
    'pe37bfdfb3c994f271e0b2',
    'pe1cb7a2233d63454a45a7',
    'pe047981e68a82dd8d6a0f',
    'pe1710e03055aa71d6cd03',
    'pe14795189ab12539577c2',
    'pe213208e63593e03d0318',
    'pe69c1728159d8f7be8607',
    'pe0b9310c667a967aa5535',
    'pe0b562c22b375af66dbd3',
    'pe9563b8defc21efed652b',
    'pe22d0a4d1b18259f58cd6',
    'pe7e378eea5aff81e6431e',
    'pe3032236247fa47c52462',
    'pe645fd676e1da1ee00250',
    'pe33f6bd8dd10c4296e3c4',
    'pe419e891b27644603c19f',
    'pe19188e21e6800b6d60bf',
    'pe4a0bde96cd6aa00232b5',
    'pe228ef24e4b632f13695a',
    'pee320496187f73f749d3a',
    'pe3d793dccdd5c792458d7',
    'pe4e080feb09c9902aa897',
    'pe0b41790c5aee283dfd69',
    'pe27b496624964e9ad7e11',
    'pe54c9a2e9ea92379d71d5',
    'pe21f114cacb01f10c5f75',
    'pe7bd5614250586bfa3856',
    'pe101fb93a6fa3fb154e67',
    'pe40ebaadc3aa4839139f8',
    'ped905ba9a83ecab76373d',
    'pef55ef839d839661bcf42',
    'pec317675c6b2ae527911e',
    'pe4c0caaed0e0ed1b8a46b',
    'pe6e00dc458d4edfd0ecf2',
    'pe400dcc18460609704c5c',
    'pe4f8071036f6390d1c718',
    'pe3fb234faedd7cc6f1f5e',
    'pe503e08de81cc5790a8e2',
    'pe3a73eddd4c853238365e',
    'pe76790d9c2749e0c928c6',
    'pe5d5f751579f463f7ec00',
    'pe10aed1f8a03214653b36',
    'pe4914af1d02ee269a8cc1',
    'pe5b100f0651fa0a89ae3b',
    'pe5417f6a3d63caf1b8692',
    'pea157cf7e20ab2beb76ab',
    'pe2fcf88bb4b804817ed6a',
    'pe7d3444c163d8c80d6d3d',
    'pedd4c66d01eabd75a1e3e',
    'pef7e79d70168b7aa0ba06',
    'pefda301547861602608bb',
    'ped67c22a46d2d49e20b08',
    'pe99cee7d0674e85f791e6',
    'pe6ed0338a942d5ae76ca6',
    'pef2097d68044010bf9231',
    'pe48d7aa641674b219e304',
    'pe628d0a143d872a606219',
    'pe421ba3204058a8d2a908',
    'pe97f6d80cd48345f0b6b6',
    'pe83ddc1cb450ec7969fbb',
    'pe130964186ade505c0eda',
    'pe9e2551b6044d75a44e45',
    'pe5f316f9d8b77ad04edc1',
    'pe5611787975f1feb7c230',
    'ped168c9ba0ab288440519',
    'pe3b0f256b5badbf30d4f1',
    'pe80bfe2ba95b9a27ee014',
    'peddf008643449815c42a6',
)
CANCIONES_PERU_RESTO = (
    'pe87cc50a8946550dd4c15',
    'ped6f2f40bd35fd9913c42',
    'pecd60ef97240904bed6e5',
    'pecc3e2f7a030debe986f8',
    'pec30afc5e7c27b1adeded',
    'pe55c14fa7477609916b5d',
    'peeba9b0ae3af0ae12eaa3',
    'pec6d3b0c0dcb0c2e26f31',
    'peda114ccd302b58075c23',
    'pef98e4dd8a1b2800501aa',
    'pee766628854fb31f42fbf',
    'pedaa9fc64de2e941c7b37',
    'pe9c28681bd71a9dd9f431',
    'peb66e6211912e3a369cf5',
    'pe92d8326bef7af842d6d1',
    'pe741f6c01afd8d9a605bc',
    'ped4ac5f278845f394fba2',
    'pefeb034d1113960a02faa',
    'pe6a50ac89acd2d699b5a7',
    'pe6afd6a0d2b255580ac31',
    'pee8d8d4dd7c1d48a64915',
    'pe601578681af2627b613c',
    'ped4c869efe711f29ca6f0',
    'pee407499aeea04a071ff1',
    'pef1aa204a1050d2a2a745',
    'pe6183191175135c32ecb1',
    'pefaf451943ce9e069b850',
    'pe9b1c0d94996728c02ece',
    'pecf27ef9a6d7239126a2a',
    'ped5f8ef659d27adca5fac',
    'pe93006e41aea0e1388407',
    'pea73cdf68df00b58ffd3b',
    'peda4595192bb1da30541f',
    'pe48b374dd89f38d84c384',
    'pea0023e6a1f22bfb2f21c',
    'pe1240d9883e244da9a939',
    'pe4e1a7d373bbee4d2b376',
    'pe88d4b36d602ec8cf6b43',
    'pe6b2786af539c813ababe',
    'pe4c2fe3dc62b902a5aefa',
    'pe860fb65ea2c75a68b598',
    'pe5c480584c8640ce88717',
    'pef6a3cce2acc5e4c14b4f',
    'peee3ccf1f660357c6db54',
    'pe0a0fc79dc44d6dfc1473',
    'pe6d089f9f3ecfe1313977',
    'pe9f76732ff384389d841f',
    'pef9bc16343d7bd2df3660',
    'pefc00f2c0eda6a1aa091d',
    'pe71f60e0c38f5755521fe',
    'pe974406db423184f209e4',
    'pefecd310cc06ca5a478de',
    'peef966db1255059e6184f',
    'pe3c41039269e90a92935f',
    'pe7aaa6e0f6f8da2459728',
    'pe9094ae86668e633cd7fd',
    'pe4880666603fa52bf0fa7',
    'pebd8ec8b0fda94d41abe3',
    'peb352e6b5bde54f323e93',
    'pe8af2c1b7b0c5ff94af42',
    'peae2fe6e5f215e71288ee',
    'pec6195f93b14e266481a9',
    'pedb0e77dd4858ac0a28d7',
    'peb411e4d6f2d5722aeecc',
    'pea1023c27e7bcb39a3cf8',
    'pe6f04d45ca6ee22183097',
    'pe93b9473f06e1bb6eb490',
    'pe511d20c6679edf673261',
    'pe106017ea03ffe9b6a44b',
    'pe8f59defee4f5beaaadc7',
    'pe011620e87eddfcce541b',
    'pe805c62b8d39952ff46eb',
    'ped193969527a209a53f0e',
    'pedfe8adfddaf25a4f1a04',
    'peb1af68b1192eabd1e6c7',
    'pe788708b03ce69d3b749a',
    'pe7819637d40b8096d819d',
    'pee2a68d3e99d8a0f3a5e3',
    'pef022618c329a12f50584',
    'pedbaea9d9b8b3fd3dfa30',
    'pe93f52d9245623fa13dae',
    'pe9ebf6649e4f7d81fa331',
    'peafcd59aa8078ea6b1ab9',
    'pe7e0c1e63418bc03d38d8',
    'pe849c04ca240b615a4070',
    'pee0bd0a65fd3834dafd80',
    'pef01c803aec5e06f547b4',
    'ped439fa97796078809823',
    'pecda5b91ad6dca9bb5aa1',
    'pe0520be716c6715265fac',
    'pef27f66a9f90994970ce6',
    'pe364b76e87bcb38266e77',
    'pef32e2d0e67364741c151',
    'peff30e30d7d190e311737',
    'peb9c54bdd253eb2d0951d',
    'pe244c0606fc1e809d9aff',
    'pe52d281cdb18548a035b2',
    'pe84db5223761f247a3fb7',
    'pe44be3353c88e1d9b552a',
    'pee0bb438725a8624e552d',
)
REPERTORIO = CANCIONES_DEMO + CANCIONES_AMPLIADAS + CANCIONES_PERU_RESTO

VERSIONES = {
    'pee0bb438725a8624e552d': 'pe551e72fc9600fdfb2596',
    'pe84db5223761f247a3fb7': 'pe59f1560018828d3aef33',
    'peb9c54bdd253eb2d0951d': 'pe972b71d09fb09f5cbf80',
    'pe244c0606fc1e809d9aff': 'pe972b71d09fb09f5cbf80',
    'pe6d089f9f3ecfe1313977': 'pe4157e2dfc863b4770742',
    'peee3ccf1f660357c6db54': 'pe5086fe0c56542c131ee0',
}


def directorio_modelo() -> Path:
    from multimedia import config
    return config.directorio_modelo('audio') / 'acapella'


def _clase_suave(semitonos: np.ndarray, pesos: np.ndarray) -> np.ndarray:
    clases = np.arange(12)
    diferencia = (semitonos[..., None] - clases) % 12
    diferencia = np.minimum(diferencia, 12 - diferencia)
    campana = np.exp(-0.5 * (diferencia / SIGMA_SEMITONOS) ** 2)
    return (campana * pesos[..., None]).sum(axis=-2)


def melodia(y: np.ndarray, picos: int = PICOS_REFERENCIA, separar: bool = True) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    if y.ndim != 1 or not len(y) or not np.isfinite(y).all():
        raise ValueError('se requiere una señal mono con muestras finitas')
    if separar:
        y = librosa.effects.harmonic(y, margin=3.0)
    cqt = np.abs(librosa.cqt(y, sr=SR, hop_length=HOP, fmin=librosa.note_to_hz(FMIN),
                             n_bins=BINS_OCTAVA * OCTAVAS_CQT, bins_per_octave=BINS_OCTAVA))
    energia_db = librosa.amplitude_to_db(cqt.sum(axis=0), ref=np.max)
    log = np.log1p(100 * cqt / (np.percentile(cqt, 99) + 1e-9))

    rango = BINS_OCTAVA * OCTAVAS_MELODIA
    saliencia = np.zeros((rango, log.shape[1]), dtype=np.float32)
    for h in range(1, ARMONICOS + 1):
        desplazamiento = int(round(BINS_OCTAVA * np.log2(h)))
        saliencia += (0.8 ** (h - 1)) * log[desplazamiento:desplazamiento + rango]
    inicio = NOTA_BAJA * BINS_OCTAVA // 12
    banda = saliencia[inicio:]

    orden = np.argsort(banda, axis=0)[::-1][:picos]
    valores = np.take_along_axis(banda, orden, axis=0)
    pesos = valores / np.maximum(valores[:1], 1e-9)
    semitonos = (orden + inicio) / (BINS_OCTAVA / 12)
    vectores = _clase_suave(semitonos.T, pesos.T)
    vectores[energia_db < SILENCIO_DB] = 0

    n = len(vectores) // AGRUPAR * AGRUPAR
    if n == 0:
        return np.zeros((0, 12), np.float32)
    vectores = vectores[:n].reshape(-1, AGRUPAR, 12).mean(axis=1)
    normas = np.linalg.norm(vectores, axis=1, keepdims=True)
    return np.divide(vectores, normas, out=np.zeros_like(vectores), where=normas > 1e-9).astype(np.float32)


def melodia_voz(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    if len(y):
        y = y - float(np.mean(y))
        pico = float(np.max(np.abs(y)))
        if pico > 0:
            y = y / pico
    return melodia(y, picos=1, separar=False)

def leer_metadatos(track_id: str) -> dict:
    ruta = CARPETA_AUDIO / f'{track_id}.json'
    if not ruta.is_file():
        raise FileNotFoundError(f'no existe {ruta}')
    m = json.loads(ruta.read_text(encoding='utf-8'))
    return {'track_id': track_id, 'titulo': m.get('track_name', track_id), 'artista': m.get('artists', ''),
            'genero': m.get('track_genre', ''), 'pais': m.get('country', ''),
            'ruta': f'bench/data/musica_propia/{m.get("file", track_id + ".wav")}'}


def buscar_ids(artistas=(), titulos=()) -> list[str]:
    ids = []
    for ruta in sorted(CARPETA_AUDIO.glob('pe*.json')):
        m = json.loads(ruta.read_text(encoding='utf-8'))
        if not isinstance(m, dict):
            continue
        artista_ok = any(a.lower() == m.get('artists', '').lower() for a in artistas)
        titulo_ok = any(t.lower() in m.get('track_name', '').lower() for t in titulos)
        if artista_ok or titulo_ok:
            ids.append(m['track_id'])
    return ids


def ruta_catalogo() -> Path:
    return directorio_modelo() / 'catalogo.json'

def cargar_catalogo(validar: bool = True) -> dict:
    ruta = ruta_catalogo()
    if not ruta.is_file():
        if validar:
            raise FileNotFoundError('no hay canciones preparadas; ejecute python -m deteccion.acapella preparar')
        return {}
    return json.loads(ruta.read_text(encoding='utf-8'))


def guardar_catalogo(catalogo: dict) -> None:
    ruta = ruta_catalogo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix('.tmp')
    temporal.write_text(json.dumps(catalogo, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(temporal, ruta)


def demucs_disponible() -> bool:
    import importlib.util
    return importlib.util.find_spec('demucs') is not None and importlib.util.find_spec('torch') is not None


_modelo_demucs = None


def separar_voz(ruta) -> np.ndarray:
    global _modelo_demucs
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    if _modelo_demucs is None:
        _modelo_demucs = get_model('htdemucs')
        _modelo_demucs.eval()
    modelo = _modelo_demucs
    y, _ = librosa.load(str(ruta), sr=modelo.samplerate, mono=True)
    x = torch.tensor(np.stack([y, y]))[None]
    media, desv = float(y.mean()), float(y.std()) + 1e-8
    with torch.no_grad():
        fuentes = apply_model(modelo, (x - media) / desv, shifts=0, split=True, overlap=0.1, progress=False)[0]
    voz = (fuentes[modelo.sources.index('vocals')] * desv + media).mean(0).numpy()
    return librosa.resample(voz, orig_sr=modelo.samplerate, target_sr=SR).astype(np.float32)


def _voz_de(track_id: str, ruta_audio, carpeta: Path):
    import soundfile as sf
    destino = carpeta / 'voces' / f'{track_id}.flac'
    if destino.is_file():
        voz, _ = sf.read(destino, dtype='float32')
        return voz
    voz = separar_voz(ruta_audio)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix('.tmp.flac')
    sf.write(temporal, voz, SR)
    os.replace(temporal, destino)
    return voz


def _preparar_una(track_id: str, carpeta: str) -> dict:
    from multimedia.mfcc import cargar_audio
    meta = leer_metadatos(track_id)
    inicio = time.perf_counter()
    ruta = RAIZ / meta['ruta']
    if demucs_disponible():
        voz = _voz_de(track_id, ruta, Path(carpeta))
        m, metodo, duracion = melodia_voz(voz), 'voz_demucs', len(voz) / SR
    else:
        y = cargar_audio(ruta, SR)
        m, metodo, duracion = melodia(y), 'mezcla', len(y) / SR
    np.save(Path(carpeta) / f'{track_id}.npy', m.astype(np.float16))
    return {**meta, 'duracion_s': round(duracion, 2), 'fotogramas': int(len(m)), 'metodo': metodo,
            'tiempo_s': round(time.perf_counter() - inicio, 2)}


def preparar(ids, workers: int | None = None, forzar: bool = False, progreso=None) -> dict:
    carpeta = directorio_modelo()
    carpeta.mkdir(parents=True, exist_ok=True)
    catalogo = cargar_catalogo(validar=False)
    mejorar = demucs_disponible()
    pendientes = [i for i in dict.fromkeys(ids)
                  if forzar or i not in catalogo or not (carpeta / f'{i}.npy').is_file()
                  or (mejorar and catalogo[i].get('metodo') == 'mezcla')]

    def registrar(tid, info, error):
        if info is not None:
            catalogo[tid] = info
            guardar_catalogo(catalogo)
            limpiar_cache()
            print(f"[acapella] {info['artista']} · {info['titulo']}: {info['fotogramas']} fotogramas "
                  f"en {info['tiempo_s']} s", flush=True)
        else:
            print(f'[acapella] {tid}: no se pudo preparar ({error})', flush=True)
        if progreso is not None:
            progreso(tid, info, error)

    if workers is None:
        workers = 0 if demucs_disponible() else max(1, min(4, (os.cpu_count() or 2) // 2))
    if workers == 0:
        for tid in pendientes:
            try:
                registrar(tid, _preparar_una(tid, str(carpeta)), None)
            except (OSError, ValueError, RuntimeError) as error:
                registrar(tid, None, str(error))
    elif pendientes:
        with ProcessPoolExecutor(workers) as pool:
            futuros = {pool.submit(_preparar_una, tid, str(carpeta)): tid for tid in pendientes}
            for futuro in as_completed(futuros):
                try:
                    registrar(futuros[futuro], futuro.result(), None)
                except (OSError, ValueError, RuntimeError) as error:
                    registrar(futuros[futuro], None, str(error))
    guardar_catalogo(catalogo)
    limpiar_cache()
    return catalogo


_preparacion = {'activa': False, 'total': 0, 'hechas': 0, 'actual': None, 'omitidas': [], 'error': None}
_preparacion_lock = threading.Lock()


def estado() -> dict:
    with _preparacion_lock:
        prep = {**_preparacion, 'omitidas': list(_preparacion['omitidas'])}
    catalogo = cargar_catalogo(validar=False)
    return {'canciones': len(catalogo), 'directorio': str(directorio_modelo()),
            'audios_disponibles': CARPETA_AUDIO.is_dir(), 'por_defecto': len(REPERTORIO),
            'preparacion': prep}


def iniciar_preparacion(ids=None, forzar: bool = False) -> bool:
    ids = list(ids or REPERTORIO)
    with _preparacion_lock:
        if _preparacion['activa']:
            return False
        _preparacion.update(activa=True, total=len(ids), hechas=0, actual=None, omitidas=[], error=None)

    def avance(tid, info, error):
        with _preparacion_lock:
            _preparacion['hechas'] += 1
            _preparacion['actual'] = info['titulo'] if info else tid
            if error:
                _preparacion['omitidas'].append({'track_id': tid, 'error': error})

    def trabajo():
        try:
            catalogo = cargar_catalogo(validar=False)
            listas = sum(1 for i in ids if i in catalogo and (directorio_modelo() / f'{i}.npy').is_file())
            with _preparacion_lock:
                _preparacion['hechas'] = 0 if forzar else listas
            preparar(ids, workers=0, forzar=forzar, progreso=avance)
        except Exception as error:
            with _preparacion_lock:
                _preparacion['error'] = str(error)
        finally:
            with _preparacion_lock:
                _preparacion['activa'] = False
                _preparacion['actual'] = None

    threading.Thread(target=trabajo, name='acapella-preparar', daemon=True).start()
    return True


def quitar(ids) -> dict:
    catalogo = cargar_catalogo(validar=False)
    for i in ids:
        catalogo.pop(i, None)
        (directorio_modelo() / f'{i}.npy').unlink(missing_ok=True)
    guardar_catalogo(catalogo)
    limpiar_cache()
    return catalogo


_cache = {}
_cache_lock = threading.Lock()


def limpiar_cache() -> None:
    with _cache_lock:
        _cache.clear()


def repertorio() -> dict:
    ruta = ruta_catalogo()
    firma = (str(ruta), ruta.stat().st_mtime_ns if ruta.is_file() else 0)
    with _cache_lock:
        if _cache.get('firma') != firma:
            carpeta = directorio_modelo()
            datos = {tid: (meta, np.load(carpeta / f'{tid}.npy').astype(np.float32))
                     for tid, meta in cargar_catalogo().items() if (carpeta / f'{tid}.npy').is_file()}
            _cache.update(firma=firma, datos=datos)
        return _cache['datos']

def _costos(consulta, referencia, transposicion):
    original = np.roll(referencia, transposicion, axis=1)
    costos = np.clip(1.0 - consulta @ original.T, 0.0, 1.0)
    costos[np.linalg.norm(consulta, axis=1) < 1e-6] = COSTO_SILENCIO
    return costos


try:
    from numba import njit, prange

    @njit(cache=True, parallel=True)
    def _dtw_final(consulta, referencia, silencio, peso):
        n, m = consulta.shape[0], referencia.shape[0]
        salida = np.empty(12)
        for t in prange(12):
            filas = np.full((3, m), np.inf)
            for i in range(n):
                actual, ant1, ant2 = i % 3, (i + 2) % 3, (i + 1) % 3
                for j in range(m):
                    if silencio[i]:
                        c = COSTO_SILENCIO
                    else:
                        s = 0.0
                        for p in range(12):
                            s += consulta[i, p] * referencia[j, (p - t + 12) % 12]
                        c = min(1.0, max(0.0, 1.0 - s))
                    if i == 0:
                        filas[actual, j] = c
                        continue
                    mejor = np.inf
                    if j >= 1 and filas[ant1, j - 1] < mejor:
                        mejor = filas[ant1, j - 1]
                    if j >= 2 and filas[ant1, j - 2] + peso < mejor:
                        mejor = filas[ant1, j - 2] + peso
                    if i >= 2 and j >= 1 and filas[ant2, j - 1] + peso < mejor:
                        mejor = filas[ant2, j - 1] + peso
                    filas[actual, j] = c + mejor
            salida[t] = filas[(n - 1) % 3].min()
        return salida
except ImportError:
    _dtw_final = None


def _costo_por_transposicion(consulta, referencia, activos) -> np.ndarray:
    if _dtw_final is not None:
        return _dtw_final(consulta.astype(np.float64), referencia.astype(np.float64), ~activos, PESO_SALTO)
    return np.array([librosa.sequence.dtw(C=_costos(consulta, referencia, t), subseq=True, backtrack=False,
                                          step_sizes_sigma=PASOS, weights_add=PESOS_PASOS)[-1].min()
                     for t in range(12)])


def comparar(consulta: np.ndarray, referencia: np.ndarray) -> dict | None:
    if len(consulta) < 8 or len(referencia) < len(consulta) // 2:
        return None
    activos = np.linalg.norm(consulta, axis=1) > 1e-6
    if activos.sum() < 8:
        return None
    t = int(np.argmin(_costo_por_transposicion(consulta, referencia, activos)))
    costos = _costos(consulta, referencia, t)
    _, camino = librosa.sequence.dtw(C=costos, subseq=True, step_sizes_sigma=PASOS, weights_add=PESOS_PASOS)
    camino = camino[::-1]
    voz = activos[camino[:, 0]]
    costo = float(costos[camino[voz, 0], camino[voz, 1]].mean())
    semitonos = t if t <= 6 else t - 12
    return {'similitud': round(1.0 - costo, 4),
            'transposicion_semitonos': semitonos,
            'original_inicio_s': round(float(camino[0, 1] * PASO_S), 2),
            'original_fin_s': round(float((camino[-1, 1] + 1) * PASO_S), 2)}


def reconocer(y: np.ndarray, sr: int = SR, top: int = 5, umbral: float = UMBRAL, margen: float = MARGEN,
              excluir=()) -> dict:
    inicio = time.perf_counter()
    y = np.asarray(y, dtype=np.float32)
    if y.ndim != 1 or not np.isfinite(y).all():
        raise ValueError('se requiere audio mono con muestras finitas')
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    duracion = len(y) / SR
    if duracion < DURACION_MIN_S:
        raise ValueError(f'canta al menos {DURACION_MIN_S:.0f} segundos')
    if duracion > DURACION_MAX_S:
        raise ValueError(f'la grabación no debe superar {DURACION_MAX_S:.0f} segundos')
    if float(np.sqrt(np.mean(y ** 2))) < 1e-4:
        raise ValueError('la grabación está en silencio')
    canciones = repertorio()
    if not canciones:
        raise FileNotFoundError('no hay canciones preparadas; ejecute python -m deteccion.acapella preparar')

    t0 = time.perf_counter()
    consulta = melodia_voz(y)
    tiempo_extraccion = time.perf_counter() - t0
    voz = float((np.linalg.norm(consulta, axis=1) > 1e-6).mean()) if len(consulta) else 0.0
    if voz < VOZ_MINIMA:
        raise ValueError('casi no se detecta voz en la grabación; acércate al micrófono y canta más fuerte')

    ranking = []
    for tid, (meta, referencia) in canciones.items():
        if tid in excluir:
            continue
        r = comparar(consulta, referencia)
        if r is not None:
            ranking.append({**meta, **r, 'porcentaje_similitud': round(100 * r['similitud'], 2)})
    ranking.sort(key=lambda r: (-r['similitud'], r['track_id']))

    mejor = ranking[0] if ranking else None
    ventaja = round(mejor['similitud'] - (ranking[1]['similitud'] if len(ranking) > 1 else 0.0), 4) if mejor else 0.0
    encontrada = bool(mejor and mejor['similitud'] >= umbral and ventaja >= margen)
    if encontrada:
        conclusion = f"Parece que cantaste «{mejor['titulo']}» de {mejor['artista']}."
    elif mejor:
        conclusion = f"No hay una coincidencia clara. La más parecida es «{mejor['titulo']}» ({mejor['porcentaje_similitud']}%)."
    else:
        conclusion = 'No se pudo comparar la grabación con ninguna canción.'
    coincidencias = [{**mejor, 'inicio_s': 0.0, 'fin_s': round(duracion, 2), 'ventaja': ventaja,
                      'metodo_verificacion': 'Melodía (CQT armónico) + DTW'}] if encontrada else []
    return {
        'modo': 'acapella', 'duracion_s': round(duracion, 2), 'coincidencias': coincidencias,
        'ranking': ranking[:top], 'segmentos': [], 'posible_coincidencia': encontrada,
        'conclusion': conclusion, 'aviso': AVISO,
        'parametros': {'umbral': umbral, 'margen': margen, 'canciones': len(canciones)},
        'metricas': {'canciones_comparadas': len(ranking), 'fotogramas_consulta': int(len(consulta)),
                     'voz_detectada': round(voz, 3), 'ventaja': ventaja,
                     'extraccion_ms': round(tiempo_extraccion * 1000, 1),
                     'tiempo_ms': round((time.perf_counter() - inicio) * 1000, 1)},
    }


def _evaluar(casos) -> tuple[list, dict]:
    filas = []
    for nombre, y, esperado, excluir in casos:
        res = reconocer(y, top=10_000, excluir=excluir)
        ids = [r['track_id'] for r in res['ranking']]
        pos = ids.index(esperado) + 1 if esperado in ids else None
        primero = res['ranking'][0]
        filas.append({'caso': nombre, 'posicion': pos,
                      'similitud_correcta': res['ranking'][pos - 1]['similitud'] if pos else None,
                      'primero': f"{primero['artista']} · {primero['titulo']}",
                      'similitud_primero': primero['similitud'], 'ventaja': res['metricas']['ventaja'],
                      'detectada': res['posible_coincidencia'], 'tiempo_ms': res['metricas']['tiempo_ms']})
        f = filas[-1]
        print(f"{nombre[:50]:50s} pos={pos}  correcta={f['similitud_correcta']}  "
              f"1.º={f['primero'][:40]} ({f['similitud_primero']})  {f['tiempo_ms']} ms", flush=True)
    posiciones = [f['posicion'] for f in filas]
    resumen = {'casos': len(filas), 'top1': sum(p == 1 for p in posiciones),
               'top3': sum(p is not None and p <= 3 for p in posiciones),
               'detectadas_correctas': sum(f['detectada'] and f['posicion'] == 1 for f in filas),
               'detectadas_incorrectas': sum(f['detectada'] and f['posicion'] != 1 for f in filas)}
    print(json.dumps(resumen, ensure_ascii=False))
    return filas, resumen


def evaluar_versiones(duracion_s: float = 20.0, inicios=(30.0, 75.0)) -> tuple[list, dict]:
    from multimedia.mfcc import cargar_audio
    catalogo = cargar_catalogo()
    casos = []
    for otra, esperado in VERSIONES.items():
        if esperado not in catalogo:
            continue
        meta = leer_metadatos(otra)
        y = cargar_audio(RAIZ / meta['ruta'], SR)
        for t in inicios:
            tramo = y[int(t * SR):int((t + duracion_s) * SR)]
            if len(tramo) >= duracion_s * SR * 0.9:
                casos.append((f"{meta['titulo']} @{t:.0f}s", tramo, esperado, (otra,)))
    return _evaluar(casos)


def evaluar_carpeta(carpeta) -> tuple[list, dict]:
    from multimedia.mfcc import cargar_audio
    casos = [(ruta.name, cargar_audio(ruta, SR), ruta.stem.split('__')[0], ())
             for ruta in sorted(Path(carpeta).iterdir()) if ruta.is_file() and '__' in ruta.stem]
    if not casos:
        raise SystemExit(f'no hay archivos <track_id>__nombre.ext en {carpeta}')
    return _evaluar(casos)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='orden', required=True)
    p = sub.add_parser('preparar', help='calcula la melodía de las canciones del repertorio')
    p.add_argument('--id', action='append', default=[], help='track_id (se puede repetir)')
    p.add_argument('--artista', action='append', default=[], help='todas las canciones de un artista')
    p.add_argument('--titulo', action='append', default=[], help='canciones cuyo título contiene el texto')
    p.add_argument('--workers', type=int, default=None)
    p.add_argument('--forzar', action='store_true', help='recalcula aunque ya estén preparadas')
    q = sub.add_parser('quitar', help='quita canciones del repertorio')
    q.add_argument('ids', nargs='+')
    sub.add_parser('listar', help='muestra el repertorio')
    b = sub.add_parser('buscar', help='reconoce una grabación')
    b.add_argument('archivo')
    b.add_argument('--top', type=int, default=5)
    sub.add_parser('evaluar-versiones', help='consulta con otras versiones de canciones del repertorio')
    e = sub.add_parser('evaluar', help='evalúa grabaciones propias <track_id>__*.wav')
    e.add_argument('carpeta')
    args = ap.parse_args(argv)

    if args.orden == 'preparar':
        ids = list(args.id) + buscar_ids(args.artista, args.titulo) or list(REPERTORIO)
        catalogo = preparar(ids, args.workers, args.forzar)
        print(f'[acapella] {len(catalogo)} canciones en {directorio_modelo()}')
    elif args.orden == 'quitar':
        print(f'[acapella] quedan {len(quitar(args.ids))} canciones')
    elif args.orden == 'listar':
        for tid, m in sorted(cargar_catalogo().items(), key=lambda par: (par[1]['artista'], par[1]['titulo'])):
            print(f"{tid}  {m['artista']} · {m['titulo']}  ({m['duracion_s']:.0f} s)")
    elif args.orden == 'buscar':
        from multimedia.mfcc import cargar_audio
        res = reconocer(cargar_audio(args.archivo, SR), top=args.top)
        print(res['conclusion'])
        for i, r in enumerate(res['ranking'], 1):
            print(f"{i}. {r['porcentaje_similitud']:6.2f}%  {r['artista']} · {r['titulo']}  "
                  f"(tono {r['transposicion_semitonos']:+d}, original {r['original_inicio_s']:.0f}–"
                  f"{r['original_fin_s']:.0f} s)")
        print(json.dumps(res['metricas'], ensure_ascii=False))
    elif args.orden == 'evaluar-versiones':
        evaluar_versiones()
    elif args.orden == 'evaluar':
        evaluar_carpeta(args.carpeta)


if __name__ == '__main__':
    main()
