"""Embeddings de frases con all-MiniLM-L6-v2 (sentence-transformers) en onnxruntime.

El vector de una frase es el promedio de los vectores de sus tokens (mean pooling) normalizado
a norma 1, como en sentence-transformers.
"""
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
DIR_MODELO = RAIZ / 'data' / 'modelos' / 'minilm'
URL_BASE = 'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/'
ARCHIVOS = {'model.onnx': ('onnx/model.onnx', '6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452'),
            'tokenizer.json': ('tokenizer.json', 'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037')}
DIMENSION = 384


def _asegurar_modelo():
    import hashlib
    from data.preparar_amazon import descargar
    for nombre, (remoto, huella) in ARCHIVOS.items():
        ruta = DIR_MODELO / nombre
        descargar(URL_BASE + remoto, str(ruta))
        if hashlib.sha256(ruta.read_bytes()).hexdigest() != huella:
            ruta.unlink()
            raise ValueError(f'{nombre} no coincide con la huella esperada; se borro para bajarlo de nuevo')


class Codificador:
    def __init__(self, max_tokens: int = 128):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        _asegurar_modelo()
        self.tokenizer = Tokenizer.from_file(str(DIR_MODELO / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_tokens)
        self.tokenizer.enable_padding()
        self.sesion = ort.InferenceSession(str(DIR_MODELO / 'model.onnx'), providers=['CPUExecutionProvider'])

    def __call__(self, textos, lote: int = 64) -> np.ndarray:
        salida = np.zeros((len(textos), DIMENSION), dtype=np.float32)
        for i in range(0, len(textos), lote):
            codificados = self.tokenizer.encode_batch(list(textos[i:i + lote]))
            ids = np.array([c.ids for c in codificados], dtype=np.int64)
            mascara = np.array([c.attention_mask for c in codificados], dtype=np.int64)
            tokens = self.sesion.run(['last_hidden_state'], {'input_ids': ids, 'attention_mask': mascara,
                                                            'token_type_ids': np.zeros_like(ids)})[0]
            suma = (tokens * mascara[:, :, None]).sum(axis=1)
            promedio = suma / np.maximum(mascara.sum(axis=1, keepdims=True), 1)
            salida[i:i + len(codificados)] = promedio / np.maximum(np.linalg.norm(promedio, axis=1, keepdims=True), 1e-12)
        return salida


MAX_TOKENS = 256
FIRMA = f"{ARCHIVOS['model.onnx'][1][:16]}-{MAX_TOKENS}"
_codificador = None


def codificador() -> Codificador:
    global _codificador
    if _codificador is None:
        _codificador = Codificador(MAX_TOKENS)
    return _codificador


def registrar() -> None:
    """Registra 'minilm' en el motor como extractor textual: SIMILAR_TO recibe el texto de la consulta."""
    from query.conexion import registrar_extractor
    registrar_extractor('minilm', lambda texto, **_: codificador()([texto])[0], texto=True)


def vectores_catalogo(claves, textos, cache: Path) -> dict:
    """Embedding de cada texto por clave; de la cache se reutilizan las claves que ya estaban."""
    previos = {}
    if cache.exists():
        with np.load(cache) as f:
            if str(f['firma']) == FIRMA:
                previos = dict(zip(f['claves'].tolist(), f['vectores']))
    faltan = [(c, t) for c, t in zip(claves, textos) if c not in previos]
    if faltan:
        previos.update(zip([c for c, _ in faltan], codificador()([t for _, t in faltan])))
    vectores = {c: previos[c] for c in claves}
    temporal = cache.with_name(cache.stem + '.tmp.npz')
    np.savez(temporal, claves=np.array(list(vectores)), vectores=np.stack(list(vectores.values())), firma=np.array(FIRMA))
    temporal.replace(cache)
    return vectores
