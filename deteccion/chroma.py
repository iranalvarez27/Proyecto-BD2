from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import tempfile

import librosa
import numpy as np

from multimedia.mfcc import cargar_audio

SR = 22050
HOP = 1024
AGRUPAR = 11
PASO = AGRUPAR * HOP / SR
UMBRAL = .85


def extraer_chroma(y):
    y = np.asarray(y, dtype=np.float32)
    if not len(y) or np.sqrt(np.mean(y ** 2)) < 1e-4:
        return np.zeros((max(1, int(np.ceil(len(y) / SR / PASO))), 12), np.float32)
    cromas = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP,
                                      bins_per_octave=24, norm=None)
    cromas = np.stack([cromas[:, i:i + AGRUPAR].mean(axis=1)
                       for i in range(0, cromas.shape[1], AGRUPAR)])
    cromas /= np.maximum(np.linalg.norm(cromas, axis=1, keepdims=True), 1e-9)
    return np.asarray(cromas, dtype=np.float32)


@lru_cache(maxsize=256)
def chroma_original(ruta, firma, cache_dir):
    identidad = json.dumps([1, ruta, firma, librosa.__version__], separators=(',', ':'))
    clave = hashlib.sha256(identidad.encode('utf-8')).hexdigest()
    destino = Path(cache_dir) / (clave + '.npy')
    try:
        datos = np.load(destino, allow_pickle=False)
        if (datos.ndim == 2 and datos.shape[1] == 12 and len(datos)
                and datos.dtype == np.float32 and np.isfinite(datos).all()):
            return datos
    except (OSError, ValueError):
        pass
    datos = extraer_chroma(cargar_audio(ruta, SR))
    temporal = None
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('wb', dir=destino.parent, suffix='.tmp', delete=False) as archivo:
            temporal = Path(archivo.name)
            np.save(archivo, datos, allow_pickle=False)
        os.replace(temporal, destino)
    except OSError:
        pass
    finally:
        if temporal is not None:
            try:
                temporal.unlink(missing_ok=True)
            except OSError:
                pass
    return datos


def alinear_chroma(consulta, referencia):
    if min(len(consulta), len(referencia)) < 8:
        return None
    if np.mean(np.std(consulta, axis=0)) < .015 or np.mean(np.std(referencia, axis=0)) < .015:
        return None
    mejor = None
    pasos = np.array([[1, 1], [1, 2], [2, 1]])
    for desplazamiento in range(12):
        original = np.roll(referencia, desplazamiento, axis=1)
        costos = np.clip(1 - consulta @ original.T, 0, 1)
        try:
            _, camino = librosa.sequence.dtw(C=costos, subseq=True,
                step_sizes_sigma=pasos, weights_add=np.array([0., .05, .05]))
        except librosa.util.exceptions.ParameterError:
            continue
        cobertura = len(np.unique(camino[:, 0])) / len(consulta)
        if cobertura < .8:
            continue
        q = consulta[camino[:, 0]].astype(np.float64)
        r = original[camino[:, 1]].astype(np.float64)
        q -= q.mean(axis=0)
        r -= r.mean(axis=0)
        dinamico = max(0., float(np.sum(q * r) / max(np.linalg.norm(q) * np.linalg.norm(r), 1e-9)))
        tonal = 1 - float(costos[camino[:, 0], camino[:, 1]].mean())
        score = float(np.clip(.5 * tonal + .5 * dinamico, 0, 1))
        if mejor is None or score > mejor['similitud']:
            mejor = dict(similitud=score, similitud_tonal=tonal, similitud_dinamica=dinamico,
                         transposicion_semitonos=desplazamiento if desplazamiento <= 6 else desplazamiento - 12,
                         cobertura_tonal=cobertura, camino=camino[::-1])
    return mejor


def intervalos_libres(inicio, fin, eventos, pista=None):
    libres = [(inicio, fin)]
    for evento in eventos:
        if pista is not None and evento['track_id'] != pista:
            continue
        siguientes = []
        for a, b in libres:
            izquierda, derecha = evento['inicio_s'], evento['fin_s']
            if derecha <= a or izquierda >= b:
                siguientes.append((a, b))
            else:
                if a < izquierda:
                    siguientes.append((a, izquierda))
                if derecha < b:
                    siguientes.append((derecha, b))
        libres = siguientes
    return libres


def verificar_tonal(y, sr, hits, params, resolver, cache_dir, existentes):
    duracion = len(y) / sr
    if duracion < 10 or sum(b - a for a, b in intervalos_libres(0, duracion, existentes)) < 2:
        return []
    votos = defaultdict(dict)
    for hit in hits:
        if hit['similitud'] >= params.umbral:
            pista, instante = hit['track_id'], hit['consulta_s']
            votos[pista][instante] = max(votos[pista].get(instante, 0.), hit['similitud'])
    candidatos = sorted(votos, key=lambda p: (-len(votos[p]), -np.mean(list(votos[p].values())), p))[:20]
    if not candidatos:
        return []
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    consulta = extraer_chroma(y)
    largo = min(len(consulta), max(20, round(15 / PASO)))
    salto = max(1, round(10 / PASO))
    inicios = sorted(set(range(0, max(1, len(consulta) - largo + 1), salto)) | {len(consulta) - largo})
    propuestas = []
    for pista in candidatos:
        ruta = Path(resolver(pista)).resolve()
        info = ruta.stat()
        firma = (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)
        referencia = chroma_original(str(ruta), firma, str(cache_dir))
        for a in inicios:
            qi, qf = float(a * PASO), min(duracion, float((a + largo) * PASO))
            if not intervalos_libres(qi, qf, existentes, pista):
                continue
            alineacion = alinear_chroma(consulta[a:a + largo], referencia)
            if alineacion is None or alineacion['similitud'] < UMBRAL:
                continue
            camino = alineacion.pop('camino')
            ri = float(camino[0, 1] * PASO)
            rf = float((camino[-1, 1] + 1) * PASO)
            velocidad = (rf - ri) / (qf - qi)
            propuestas.append(dict(**alineacion, track_id=pista, inicio_s=qi, fin_s=qf,
                contexto_inicio_s=qi, contexto_fin_s=qf, velocidad=velocidad,
                desplazamiento_s=ri - velocidad * qi,
                metodo_verificacion='Chroma CQT + DTW',
                instantes_voto=[float((a + k) * PASO) for k in np.unique(camino[:, 0])]))
    nuevos = []
    for propuesta in sorted(propuestas, key=lambda p: -p['similitud']):
        for a, b in intervalos_libres(propuesta['inicio_s'], propuesta['fin_s'], existentes + nuevos,
                                     propuesta['track_id']):
            instantes = [t for t in propuesta['instantes_voto'] if a <= t < b]
            if b - a < 2 or len(instantes) < params.min_votos:
                continue
            velocidad, offset = propuesta['velocidad'], propuesta['desplazamiento_s']
            nuevos.append(dict(**{**propuesta, 'inicio_s': a, 'fin_s': b, 'instantes_voto': instantes},
                evidencia_inicio_s=a, evidencia_fin_s=b, votos=len(instantes),
                porcentaje_similitud=round(100 * propuesta['similitud'], 2),
                original_inicio_s=max(0., offset + velocidad * a),
                original_fin_s=max(0., offset + velocidad * b)))
    return sorted(nuevos, key=lambda e: (e['inicio_s'], e['track_id']))
