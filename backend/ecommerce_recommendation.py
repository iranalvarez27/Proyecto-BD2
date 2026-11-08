"""API REST de la tienda y el recomendador multimodal."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from recomendacion.recomendador import Servicio, PESOS


class SolicitudRecomendacion(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    product_id: int = Field(gt=0)
    k: int = Field(default=10, ge=1, le=50)
    pesos: dict[str, float] = Field(default_factory=lambda: dict(PESOS))
    metodo: Literal['HNSW', 'IVF', 'EXACT'] = 'HNSW'
    metrica: Literal['cosine', 'euclidean', 'dot'] = 'cosine'
    texto: Literal['BM25', 'TF_IDF'] = 'BM25'
    categoria: str = Field(default='', max_length=120)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    solo_stock: bool = False

    @model_validator(mode='after')
    def coherencia(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError('Indique latitud y longitud juntas')
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError('El precio mínimo supera el máximo')
        from recomendacion.fusion import fusionar
        fusionar({}, self.pesos)
        return self


class Interaccion(BaseModel):
    usuario_id: int = Field(gt=0, le=2147483647)
    producto_id: int = Field(gt=0, le=2147483647)
    tipo: Literal['vista', 'carrito']


class ItemCompra(BaseModel):
    producto_id: int = Field(gt=0, le=2147483647)
    tienda_id: int = Field(gt=0, le=2147483647)
    cantidad: int = Field(ge=1, le=100)


class Compra(BaseModel):
    usuario_id: int = Field(gt=0, le=2147483647)
    solicitud: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    items: list[ItemCompra] = Field(min_length=1, max_length=20)


def crear_router(engine):
    router = APIRouter(prefix='/api/ecommerce', tags=['E-commerce'])
    servicio = Servicio(engine.conexion)

    def ejecutar(funcion, *args, **kwargs):
        try:
            with servicio.lock:
                return funcion(*args, **kwargs)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)) from error

    @router.get('/status')
    def status():
        return ejecutar(servicio.estado)

    @router.get('/catalog')
    def catalog(category: str = Query(default='', max_length=120), search: str = Query(default='', max_length=500),
                limit: int = Query(default=24, ge=1, le=100), after_id: int = Query(default=0, ge=0),
                cursor: str = Query(default='', max_length=100), min_price: int | None = Query(default=None, ge=0),
                max_price: int | None = Query(default=None, ge=0)):
        if min_price is not None and max_price is not None and min_price > max_price:
            raise HTTPException(422, 'El precio mínimo supera el máximo')
        return ejecutar(servicio.catalogo, category, search, limit, after_id, cursor, min_price, max_price)

    @router.get('/products/{product_id}')
    def product(product_id: int):
        return ejecutar(servicio.detalle, product_id)

    @router.post('/recommend')
    def recommend(req: SolicitudRecomendacion):
        datos = req.model_dump()
        pid = datos.pop('product_id')
        return ejecutar(servicio.recomendar, pid, **datos)

    @router.get('/products/{product_id}/stores')
    def stores(product_id: int, lat: float | None = Query(default=None, ge=-90, le=90),
               lon: float | None = Query(default=None, ge=-180, le=180)):
        if (lat is None) != (lon is None):
            raise HTTPException(422, 'Indique latitud y longitud juntas')
        from recomendacion.disponibilidad import tiendas_con_stock
        from recomendacion.repositorio import Repositorio
        def consultar():
            servicio.detalle(product_id)
            repo = Repositorio(engine.conexion)
            return {'tiendas': tiendas_con_stock(repo, product_id, lat, lon), 'trazas': repo.trazas}
        return ejecutar(consultar)

    @router.post('/interactions')
    def interaction(req: Interaccion):
        from recomendacion.compras import registrar_interaccion
        return ejecutar(registrar_interaccion, engine.conexion, **req.model_dump())

    @router.post('/purchases')
    def purchase(req: Compra):
        from recomendacion.compras import comprar
        return ejecutar(comprar, engine.conexion, **req.model_dump())

    return router
