import librosa
import numpy as np
import shutil
import subprocess

from .config import HOP, N_FFT, N_MFCC, SEG_S, SR


def cargar_audio(ruta, sr: int = SR) -> np.ndarray:
    try:
        y, _ = librosa.load(str(ruta), sr=sr, mono=True)
        return y
    except (OSError, RuntimeError) as error:


        ejecutable = shutil.which("ffmpeg")
        if ejecutable is None:
            raise RuntimeError("No se pudo decodificar el audio; se requiere FFmpeg como alternativa") from error
        try:
            resultado = subprocess.run(
                [ejecutable, "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(ruta),
                 "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(sr), "pipe:1"],
                capture_output=True, check=True, timeout=180,
            )
        except (subprocess.SubprocessError, OSError) as fallo:
            detalle = getattr(fallo, "stderr", b"") or b""
            raise RuntimeError("No se pudo recuperar el audio con FFmpeg: " +
                               detalle.decode("utf-8", errors="replace")[-400:]) from error
        y = np.frombuffer(resultado.stdout, dtype="<f4").copy()
        if not len(y) or not np.isfinite(y).all():
            raise ValueError("El archivo no contiene audio recuperable")
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

    return np.ascontiguousarray(m[1:].T, dtype=np.float32)


def reducir_ruido_estacionario(y, n_fft: int = N_FFT, hop: int = HOP):


    y = np.asarray(y, dtype=np.float32)
    if len(y) < n_fft:
        return y.copy()
    espectro = librosa.stft(y, n_fft=n_fft, hop_length=hop)
    potencia = np.abs(espectro)**2
    piso = float(np.median(potencia[3 * len(potencia) // 4:])) / np.log(2)
    if piso <= 1e-12:
        return y.copy()
    limpia = np.maximum(potencia - piso, .02 * potencia)
    ganancia = np.sqrt(np.divide(limpia, potencia, out=np.zeros_like(potencia), where=potencia > 0))
    return np.asarray(librosa.istft(espectro * ganancia, hop_length=hop, length=len(y)), dtype=np.float32)
