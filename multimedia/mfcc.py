import librosa
import numpy as np

from .config import HOP, N_FFT, N_MFCC, SEG_S, SR


def cargar_audio(ruta, sr: int = SR) -> np.ndarray:
    y, _ = librosa.load(str(ruta), sr=sr, mono=True)
    return y


def segmentos_de_senal(y, sr: int = SR, seg_s: float = SEG_S) -> list[np.ndarray]:
    if seg_s <= 0:
        raise ValueError("seg_s debe ser positivo")
    y = np.asarray(y, dtype=np.float32)
    if y.ndim != 1:
        raise ValueError("y debe ser una senal mono de una dimension")
    largo = int(seg_s * sr)
    if largo <= 0:
        raise ValueError("el segmento debe tener al menos una muestra")
    return [y[i:i + largo] for i in range(0, max(0, len(y) - largo + 1), largo)]


def segmentar(ruta, sr: int = SR, seg_s: float = SEG_S) -> list[np.ndarray]:
    return segmentos_de_senal(cargar_audio(ruta, sr), sr, seg_s)


def extraer_mfcc(y, sr: int = SR, n_fft: int = N_FFT, hop: int = HOP,
                 n_mfcc: int = N_MFCC) -> np.ndarray:
    if n_mfcc < 2:
        raise ValueError("n_mfcc debe ser al menos 2 (se descarta c0)")

    y = np.asarray(y, dtype=np.float32)
    if y.ndim != 1:
        raise ValueError("y debe ser una senal mono de una dimension")
    if y.size == 0:
        return np.empty((0, n_mfcc - 1), np.float32)

    m = librosa.feature.mfcc(
        y=y, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop,
    )
    if m.shape[0] <= 1:
        return np.empty((0, n_mfcc - 1), np.float32)
    # librosa devuelve (coeficientes, tiempo); una fila por ventana.
    return np.ascontiguousarray(m[1:].T, dtype=np.float32)
