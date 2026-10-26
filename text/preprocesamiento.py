import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache

from nltk.stem.snowball import SnowballStemmer

IDIOMAS = ("spanish", "english")
IDIOMA_POR_DEFECTO = "spanish"
MAX_LARGO_TERMINO = 50

_DIR_STOPWORDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stopwords")

_DIACRITICOS = re.compile(r"(?<!n)[\u0300-\u036f]|(?<=n)[\u0300-\u0302\u0304-\u036f]")
_SIGLA = re.compile(r"\b(?:[a-zñ]\.){2,}(?:[a-zñ]\b)?")
_TOKEN = re.compile(r"[a-zñ0-9]+")


def _validar_idioma(idioma: str) -> None:
    if idioma not in IDIOMAS:
        raise ValueError(f"idioma '{idioma}' no soportado (disponibles: {', '.join(IDIOMAS)})")


def quitar_tildes(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto)
    return unicodedata.normalize("NFC", _DIACRITICOS.sub("", texto))


def normalizar(texto: str) -> str:
    texto = quitar_tildes(texto.lower())
    return _SIGLA.sub(lambda m: m.group().replace(".", ""), texto)


def tokenizar(texto: str) -> list[str]:
    return [t for t in _TOKEN.findall(texto) if (len(t) > 1 or t.isdigit()) and len(t) <= MAX_LARGO_TERMINO]


@lru_cache(maxsize=None)
def stopwords(idioma: str = IDIOMA_POR_DEFECTO) -> frozenset:
    _validar_idioma(idioma)
    with open(os.path.join(_DIR_STOPWORDS, f"{idioma}.txt"), encoding="utf-8") as f:
        return frozenset(normalizar(linea.strip()) for linea in f if linea.strip())


@lru_cache(maxsize=None)
def _stemmer(idioma: str) -> SnowballStemmer:
    _validar_idioma(idioma)
    return SnowballStemmer(idioma)


@lru_cache(maxsize=500_000)
def raiz(palabra: str, idioma: str = IDIOMA_POR_DEFECTO) -> str:
    return _stemmer(idioma).stem(palabra)


def preprocesar(texto: str, idioma: str = IDIOMA_POR_DEFECTO, stemming: bool = True) -> list[str]:
    vacias = stopwords(idioma)
    terminos = [t for t in tokenizar(normalizar(texto)) if t not in vacias]
    if stemming:
        terminos = [raiz(t, idioma) for t in terminos]
    return terminos


def contar_terminos(texto: str, idioma: str = IDIOMA_POR_DEFECTO, stemming: bool = True) -> dict[str, int]:
    return dict(Counter(preprocesar(texto, idioma, stemming)))
