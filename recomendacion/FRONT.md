# Front de la tienda (opción B): qué debe tener

Guía para construir el front de la tienda en un repo aparte. El backend está en este repo y el
contrato exacto (parámetros, validaciones, respuestas) se lee en:

- `backend/ecommerce_recommendation.py`: rutas y modelos de request (prefijo `/api/ecommerce`).
- `recomendacion/recomendador.py`: forma de las respuestas de catálogo, ficha, búsqueda y recomendación.
- `recomendacion/disponibilidad.py`: tiendas, stock y localizador.
- `recomendacion/compras.py`: compras e interacciones.

## Contexto

- Tienda de electrónica en **EE. UU.**: la interfaz va en **inglés** y los precios en **USD**.
  Los precios llegan en **centavos** (`precio_centavos`).
- ~30 000 productos en 9 categorías, compras reales de Amazon, 1000 sucursales simuladas.
- Las fotos se piden al backend con el campo `media_url` de cada producto (ruta `/api/media/...`).
- En desarrollo, proxy de `/api` a `http://127.0.0.1:8000`, como en `frontend/vite.config.js` de
  este repo. El backend tiene CORS abierto.
- Sin login: el usuario es un id numérico de demo guardado en `localStorage`.
- `GET /api/ecommerce/status` dice si la tienda está preparada (`listo`). Si no lo está, mostrar
  un aviso en vez de páginas vacías.

## Páginas y funcionalidades

### 1. Inicio
- **Barra de búsqueda** (visible en todo el sitio). `GET /catalog?search=...`: búsqueda híbrida
  (BM25 + embeddings + popularidad); el orden ya viene resuelto.
- **Las 9 categorías** como tarjetas o menú. La lista viene en `categorias` de `GET /catalog`.
- **Best sellers:** global y por categoría, `GET /best-sellers?category=&limit=`. Cada producto
  trae `compradores`.

### 2. Listado (categoría o resultados de búsqueda)
- `GET /catalog` con `category`, `search`, `min_price`, `max_price` (en centavos) y `limit`.
- **Paginación por cursor** ("load more"): se pasa el `next_cursor` de la respuesta anterior. Sin
  búsqueda va como `after_id`; con búsqueda, como `cursor`. Si cambian los filtros se empieza de
  nuevo.
- Filtro de precio y de categoría.

### 3. Ficha de producto
- Datos y descripción: `GET /products/{id}`.
- **"You may also like":** `POST /recommend` con `product_id`, `k` (10) y la ubicación del usuario
  (`lat`, `lon`). Cada recomendación trae `aportes_pct`: cuánto aportó cada señal (`visual`,
  `texto`, `metadata`, `compras`). **Mostrarlo** (por ejemplo, una barrita o chips con los
  porcentajes), porque es lo que distingue al recomendador híbrido en la demo.
- **Disponibilidad en tiendas cercanas:** `GET /products/{id}/stores?lat=&lon=` devuelve las
  tiendas más cercanas **con stock**, con distancia (`dist_m`) y unidades. También vienen dentro
  de cada producto de `/recommend` (`tiendas`).
- Agregar al carrito eligiendo la tienda donde se retira (por defecto, la más cercana con stock).

### 4. Carrito y compra
- `POST /purchases` con `usuario_id`, `solicitud` e `items` (`producto_id`, `tienda_id`, `cantidad`).
- `solicitud` es una **clave única por intento de compra** (por ejemplo, un uuid sin guiones): si
  se reintenta con la misma clave, el backend devuelve la misma respuesta sin cobrar dos veces.
- Si no hay stock suficiente responde 400 con el detalle; mostrarlo.
- Después de comprar, las recomendaciones de esos productos cambian (se actualizan las
  co-compras). Sirve para la demo.

### 5. Tiendas
- **Mapa** con las 1000 sucursales: `GET /stores` (la `ubicacion` viene como `[lat, lon]`).
  Sirve Leaflet con OpenStreetMap.
- **Localizador "Stores near you":** `GET /stores/nearby?lat=&lon=&k=`, las k más cercanas con su
  distancia. Es la parte espacial de la app (k-NN sobre un R-Tree), así que tiene que verse.

## Ubicación del usuario (lo menos estándar)

La demo se hace en Lima pero las tiendas están en EE. UU., así que no sirve la geolocalización
del navegador. Hace falta un **selector de ubicación** visible (por ejemplo, en el header):
- ciudades predefinidas (New York, Los Angeles, Chicago, Houston, Phoenix, Seattle, Miami…) y/o
- click en el mapa para fijar un punto.

Esa `lat`/`lon` se manda a `/recommend`, a `/products/{id}/stores` y a `/stores/nearby`, y cambia
qué tiendas aparecen como cercanas. Guardarla en `localStorage`.

## Para la presentación (muy recomendable)

- **Panel técnico desplegable:** todas las respuestas traen `trazas` con el SQL ejecutado, el plan
  (qué índice se usó: HNSW, IVF, SPIMI, R-Tree, hash, B+) y el tiempo de cada consulta.
  Mostrarlo en un panel o modal ("How this was computed") deja ver que todo pasa por nuestro
  motor.
- **Controles del recomendador** en ese panel: `metodo` (`HNSW`, `IVF`, `EXACT`) y `pesos` de las 4
  señales (sliders que sumen 1). Sirve para mostrar en vivo cómo cambia la lista.
- Mostrar `tiempo_total_ms` de la recomendación.

## Opcional

- `POST /interactions` con `tipo` `vista` o `carrito`: se registra, pero hoy no afecta las
  recomendaciones.

## Fuera de alcance (no hacer)

- Búsqueda por foto, "Recommended for you" y "Frequently bought together".
