import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.types import RID
from engine.buffer_pool import BufferPool
from index.base import Index
from index.inverted_store import EXT_DICCIONARIO, EXT_DOCUMENTOS, ArchivoDocumentos, LectorIndice, rutas
from index.spimi import MAX_POSTINGS_POR_BLOQUE, construir_spimi
from text.preprocesamiento import IDIOMA_POR_DEFECTO, IDIOMAS, preprocesar


def base_desde_archivo(ruta_diccionario: str) -> str:
    if not ruta_diccionario.endswith(EXT_DICCIONARIO):
        raise ValueError(f"'{ruta_diccionario}' no es un diccionario de indice invertido")
    return ruta_diccionario[:-len(EXT_DICCIONARIO)]


class IndiceInvertido(Index):
    def __init__(self, pool: BufferPool, base: str, idioma: str = IDIOMA_POR_DEFECTO, stemming: bool = True,
                 max_postings_bloque: int = MAX_POSTINGS_POR_BLOQUE):
        if idioma not in IDIOMAS:
            raise ValueError(f"idioma '{idioma}' no soportado (disponibles: {', '.join(IDIOMAS)})")
        self.pool = pool
        self.base = base
        self.idioma = idioma
        self.stemming = stemming
        self.max_postings_bloque = max_postings_bloque
        self.estadisticas = None
        self.lector = None
        self.documentos = None
        self._load()

    def file_paths(self) -> list[str]:
        return rutas(self.base)

    def close(self) -> None:
        for ruta in rutas(self.base):
            self.pool.close(ruta)

    def is_empty(self) -> bool:
        return self.documentos is None or len(self.documentos) == 0

    @property
    def desactualizado(self) -> bool:
        return self.documentos is not None and self.documentos.desactualizado

    def bulk_load(self, pairs) -> None:
        self.estadisticas = construir_spimi(self.pool, self.base, ((rid, texto) for texto, rid in pairs),
                                            self.idioma, self.stemming, self.max_postings_bloque)
        self._load()

    def insert(self, key: Any, rid: RID) -> None:
        self._marcar_desactualizado()

    def delete(self, key: Any, rid: RID) -> bool:
        self._marcar_desactualizado()
        return True

    def search(self, key: Any) -> list[RID]:
        raise NotImplementedError("las consultas sobre el indice invertido se hacen con MATCH")

    def range_search(self, low: Any, high: Any) -> list[RID]:
        raise NotImplementedError("un indice invertido no soporta busquedas por rango")

    def terminos_consulta(self, texto: str) -> list[str]:
        return preprocesar(texto, self.idioma, self.stemming)

    def reload(self) -> None:
        self._load()

    def _marcar_desactualizado(self) -> None:
        if self.documentos is not None:
            self.documentos.marcar_desactualizado()

    def _load(self) -> None:
        ruta_docs = self.base + EXT_DOCUMENTOS
        if self.pool.page_count(ruta_docs) == 0 or self.pool.page_count(self.base + EXT_DICCIONARIO) == 0:
            self.lector = None
            self.documentos = None
            return
        self.documentos = ArchivoDocumentos(self.pool, self.base)
        self.idioma = self.documentos.idioma
        self.stemming = self.documentos.stemming
        self.lector = LectorIndice(self.pool, self.base)
