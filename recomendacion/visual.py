"""Embeddings visuales de la tienda: ResNet-50 preentrenada en ImageNet, sin la capa de clasificacion."""
import hashlib
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
DIR_MODELOS = RAIZ / 'data' / 'modelos'
URL_MODELO = ('https://media.githubusercontent.com/media/onnx/models/main/validated/vision/'
              'classification/resnet/model/resnet50-v2-7.onnx')
SHA256_MODELO = '79102261eb6e5fd7af5d27f41316293e388c5cb691e5d25bfb035c4f64fefe31'
SALIDA_POOL = 'resnetv24_flatten0_reshape0'
DIMENSION = 2048
LADO = 224
MEDIA = np.array([0.485, 0.456, 0.406], dtype=np.float32)
DESVIO = np.array([0.229, 0.224, 0.225], dtype=np.float32)
MODOS = ('relleno', 'recorte', 'estirar', 'original')


def ruta_modelo() -> Path:
    """Modelo truncado en el pooling global, con alto y ancho de entrada libres."""
    destino = DIR_MODELOS / 'resnet50_embedding.onnx'
    if destino.exists():
        return destino
    import onnx
    from data.preparar_amazon import descargar

    original = DIR_MODELOS / 'resnet50-v2-7.onnx'
    descargar(URL_MODELO, str(original))
    if hashlib.sha256(original.read_bytes()).hexdigest() != SHA256_MODELO:
        original.unlink()
        raise ValueError(f'{original.name} no coincide con la huella esperada; se borro para bajarlo de nuevo')
    modelo = onnx.load(str(original))
    grafo = modelo.graph
    dims = grafo.input[0].type.tensor_type.shape.dim
    dims[2].dim_param, dims[3].dim_param = 'alto', 'ancho'
    # se quita la capa densa final (1000 clases) y sus pesos
    densa = next(n for n in grafo.node if SALIDA_POOL in n.input)
    grafo.node.remove(densa)
    for peso in [i for i in grafo.initializer if i.name in densa.input]:
        grafo.initializer.remove(peso)
    for entrada in [i for i in grafo.input if i.name in densa.input]:
        grafo.input.remove(entrada)
    del grafo.output[:]
    grafo.output.append(onnx.helper.make_tensor_value_info(SALIDA_POOL, onnx.TensorProto.FLOAT, ['N', DIMENSION]))
    onnx.checker.check_model(modelo)
    temporal = destino.with_suffix('.tmp')
    onnx.save(modelo, str(temporal))
    temporal.replace(destino)
    return destino


def preprocesar(imagen_bgr: np.ndarray, modo: str = 'estirar') -> np.ndarray:
    """BGR de OpenCV a tensor 3 x H x W normalizado como en ImageNet."""
    import cv2

    if modo not in MODOS:
        raise ValueError(f'modo debe ser uno de {MODOS}')
    rgb = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2RGB)
    alto, ancho = rgb.shape[:2]
    if modo == 'relleno':
        escala = LADO / max(alto, ancho)
        nuevo = (max(1, round(ancho * escala)), max(1, round(alto * escala)))
        chica = cv2.resize(rgb, nuevo, interpolation=cv2.INTER_AREA)
        rgb = np.full((LADO, LADO, 3), 255, dtype=np.uint8)
        y, x = (LADO - nuevo[1]) // 2, (LADO - nuevo[0]) // 2
        rgb[y:y + nuevo[1], x:x + nuevo[0]] = chica
    elif modo == 'recorte':
        escala = 256 / min(alto, ancho)
        rgb = cv2.resize(rgb, (round(ancho * escala), round(alto * escala)), interpolation=cv2.INTER_AREA)
        y, x = (rgb.shape[0] - LADO) // 2, (rgb.shape[1] - LADO) // 2
        rgb = rgb[y:y + LADO, x:x + LADO]
    elif modo == 'estirar':
        rgb = cv2.resize(rgb, (LADO, LADO), interpolation=cv2.INTER_AREA)
    tensor = (rgb.astype(np.float32) / 255 - MEDIA) / DESVIO
    return np.ascontiguousarray(tensor.transpose(2, 0, 1))


class ExtractorCNN:
    def __init__(self, modo: str = 'estirar'):
        import onnxruntime as ort

        if modo not in MODOS:
            raise ValueError(f'modo debe ser uno de {MODOS}')
        self.modo = modo
        self.sesion = ort.InferenceSession(str(ruta_modelo()), providers=['CPUExecutionProvider'])

    def _correr(self, lote: np.ndarray) -> np.ndarray:
        return self.sesion.run([SALIDA_POOL], {'data': lote})[0].astype(np.float32)

    def __call__(self, ruta) -> np.ndarray:
        return self.lote([ruta])[0]

    def lote(self, rutas, tam: int = 32) -> np.ndarray:
        import cv2

        vectores = np.zeros((len(rutas), DIMENSION), dtype=np.float32)
        # en modo original cada foto tiene su tamano: va de a una
        paso = 1 if self.modo == 'original' else tam
        for i in range(0, len(rutas), paso):
            tensores = []
            for ruta in rutas[i:i + paso]:
                imagen = cv2.imread(str(ruta))
                if imagen is None:
                    raise ValueError(f'no se pudo leer la imagen {ruta}')
                tensores.append(preprocesar(imagen, self.modo))
            vectores[i:i + len(tensores)] = self._correr(np.stack(tensores))
        return vectores


MODO = 'estirar'
FIRMA = f'{SHA256_MODELO[:16]}-{MODO}'
_extractor = None


def extractor() -> ExtractorCNN:
    global _extractor
    if _extractor is None:
        _extractor = ExtractorCNN(MODO)
    return _extractor


def registrar() -> None:
    """Registra 'cnn' en el motor para vectorizar consultas e inserciones de los indices de la tienda."""
    from query.conexion import registrar_extractor
    registrar_extractor('cnn', lambda ruta, **_: extractor()(ruta))


def vectores_catalogo(claves, rutas, cache: Path) -> dict:
    """Vector de cada imagen por clave; se reutiliza la cache si es del mismo catalogo."""
    if cache.exists():
        with np.load(cache) as f:
            if f['claves'].tolist() == list(claves) and str(f['firma']) == FIRMA:
                return dict(zip(claves, f['vectores']))
    vectores = extractor().lote(list(rutas))
    temporal = cache.with_name(cache.stem + '.tmp.npz')
    np.savez(temporal, claves=np.array(claves), vectores=vectores, firma=np.array(FIRMA))
    temporal.replace(cache)
    return dict(zip(claves, vectores))
