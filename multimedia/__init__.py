__all__ = [
    "ExtractFeatures",
    "Extractor",
    "construir_coleccion",
    "cargar_coleccion",
    "verificar_consistencia",
]


def __getattr__(nombre):
    if nombre in ("ExtractFeatures", "Extractor", "construir_coleccion",
                  "cargar_coleccion", "verificar_consistencia"):
        from . import bovw
        return getattr(bovw, nombre)
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
