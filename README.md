# Minigestor de Base de Datos Multimodal - BD2 (2026-2)

Sistema gestor de base de datos multimodal desarrollado desde cero, que soporta datos relacionales (tablas y almacenamiento físico), espaciales, texto y multimedia.

---

## Estructura del Proyecto

```
Proyecto-BD2/
├── backend/                  # Servidor de API REST (FastAPI) & Adaptador de motor
│   ├── engine_adapter.py     # Adaptador que conecta almacenamiento, índices y catálogo
│   └── main.py               # Endpoints REST y CORS
├── common/                   # Tipos comunes y estructuras de bajo nivel
│   ├── geo.py                # Haversine, euclidiana, punto en polígono y cotas para MBR
│   ├── datos_lima.py         # Generador de puntos de interés en Lima (demo y experimentos)
│   ├── page.py               # Slotted Page (4096 bytes)
│   ├── record.py             # Serialización binaria de registros
│   └── types.py              # Definición de tipos de datos, columnas y esquemas
├── storage/                  # Almacenamiento físico en disco
│   ├── heap_file.py          # Heap File con Slotted Pages
│   └── sequential_file.py    # Archivo Secuencial Paginado (Main + Aux / Lazy deletion)
├── index/                    # Estructuras de Indexación
│   ├── bplus_tree.py         # B+ Tree no agrupado
│   ├── clustered_bplus_tree.py # B+ Tree agrupado sobre SequentialFile
│   ├── extendible_hash.py    # Hash Dinámico Extensible
│   ├── rtree.py              # R-Tree en disco: rango, radio, k-NN, polígono
│   └── key_codec.py          # Codificación de claves binarias
├── query/                    # Motor de Consultas SQL
│   ├── lexer.py / tokens.py  # Analizador léxico
│   ├── parser.py / ast.py    # Analizador sintáctico y AST
│   ├── catalog.py            # Catálogo unificado de tablas e índices
│   ├── catalog_store.py      # Persistencia del catálogo en data/catalog.json
│   └── conexion.py           # Planificador y ejecutor de consultas
├── data/                     # Archivos de datos (.bin, .idx) y benchmarks
│   ├── generate_data.py      # Generador de datasets para Parte 1 y 2 (1K, 10K, 100K)
│   ├── bench_spatial.py      # Runner experimental: Secuencial vs R-Tree vs PostgreSQL GiST
│   ├── plot_spatial.py       # Generador de gráficas espaciales (.png) y tabla resumen
│   ├── benchmark_charts.py   # Gráficas experimentales de la Parte 1
│   ├── charts/               # Gráficas generadas en PNG para el informe
│   └── TABLA_RESUMEN_COMPARATIVA.md # Guía comparativa de técnicas
├── frontend/                 # Interfaz de Usuario (React + Vite + Leaflet + Tailwind CSS)
└── requirements.txt          # Dependencias Python
```

---

## 2.1.5 Interfaz de Usuario (Los 4 Paneles)

1. **Panel de Archivos (Izquierda):**
   * Inspección de tablas cargadas (`HEAP` y `SEQUENTIAL`).
   * Columnas, tipos de datos (`INT`, `VARCHAR`, etc.) y llaves primarias.
   * Índices activos (B+ Tree Agrupado, B+ Tree No Agrupado, Extendible Hash).
   * Métricas de disco en vivo: conteo de páginas de 4KB, conteo de tuplas y ratio de espacio desperdiciado por eliminación lazy.
   * Botón de **Reorganización** automática cuando el desperdicio supera el 30%.

2. **Panel de Consultas (Superior Centro):**
   * Editor de sentencias SQL multilínea con atajo `Cmd/Ctrl + Enter`.
   * Menú desplegable con plantillas rápidas (`SELECT`, `INSERT`, `ORDER BY`, `TRANSACTIONS`).
   * Botones: **Ejecutar**, **Cargar CSV** y **Limpiar** (usa `EXPLAIN` / `EXPLAIN ANALYZE` directamente en la consola SQL para ver el plan de ejecución).
   * Historial de consultas ejecutadas.

3. **Panel de Resultados (Inferior Centro):**
   * Tabla dinámica de resultados con formateo de tipos y números de fila.
   * Indicadores de latencia (`ms`) y número de filas devueltas/afectadas.
   * Exportación instantánea a **CSV** o **JSON**.
   * Detección y visualización amigable de errores.

4. **Panel del Plan de Ejecución (Pestaña dedicada):**
   * Representación visual en árbol de la estrategia del planificador de consultas.
   * Muestra nodos jerárquicos: `IndexScan (B+ Tree Agrupado)`, `IndexScan (B+ Tree No Agrupado)`, `IndexScan (Extendible Hash)`, `SequentialBinarySearch`, `FullTableScan`, `Sort (ORDER BY)`.
   * Costos estimados de E/S y conteo de filas estimadas.

---

## 2.1.6 Comparación Experimental de Técnicas (Guía de Benchmark)

Esta sección permite reproducir los experimentos comparativos requeridos en la rúbrica entre las técnicas de almacenamiento físico e indexación.

### Paso 1: Generar Datasets Sintéticos (1K, 10K, 100K)
Usa el script `data/generate_data.py` para poblar las tablas con datos realistas:
```bash
# Modo interactivo (menú en consola):
python3 data/generate_data.py

# O por argumento directo:
python3 data/generate_data.py --size 1k     # 1 000 registros
python3 data/generate_data.py --size 10k    # 10 000 registros (recomendado)
python3 data/generate_data.py --size 100k   # 100 000 registros
python3 data/generate_data.py --stats       # Ver espacio en disco ocupado
python3 data/generate_data.py --reset       # Restaurar a datos de muestra iniciales
```

> **Métricas obtenidas en este paso:** El generador mide y reporta en consola:
> * **Tiempo de inserción masiva** (HeapFile vs SequentialFile).
> * **Tiempo de construcción de índices** (B+ no agrupado, Hash dinámico, B+ agrupado).
> * **Espacio en disco utilizado y espacio adicional requerido** (tamaño en KB/MB de `.bin` y `.idx`).

---

### Paso 2: Iniciar Servidores
```bash
# Terminal 1 - Backend:
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 - Frontend:
cd frontend && pnpm dev
```

---

### Paso 3: Consultas de Evaluación en el Frontend

Abre `http://localhost:5173` y ejecuta las siguientes consultas para recolectar métricas en el **Panel de Resultados** (tiempo en `ms`) y **Panel de Plan de Ejecución**:

#### A. Búsquedas por Igualdad Exacta
* **B+ Tree No Agrupado (en HeapFile):**
  ```sql
  SELECT * FROM estudiantes WHERE id = 500;
  ```
  *Plan:* `IndexScan (B+ Tree No Agrupado)`. Acceso por RID a la página de datos.
* **Hash Dinámico (en HeapFile):**
  ```sql
  SELECT * FROM estudiantes WHERE carrera = 'Ciencia de Datos';
  ```
  *Plan:* `IndexScan (Extendible Hash)`. Búsqueda directa en bucket $O(1)$.
* **B+ Tree Agrupado (en SequentialFile):**
  ```sql
  SELECT * FROM cursos WHERE codigo = 500;
  ```
  *Plan:* `IndexScan (B+ Tree Agrupado)`. Acceso directo a la página de datos sin RID secundario.

#### B. Búsquedas por Rango
* **B+ Tree No Agrupado:**
  ```sql
  SELECT * FROM estudiantes WHERE id >= 100 AND id <= 200;
  ```
  *Plan:* `IndexScan (B+ Tree No Agrupado)`. Recorre la cadena de hojas del árbol y lee páginas de datos.
* **B+ Tree Agrupado:**
  ```sql
  SELECT * FROM cursos WHERE codigo >= 100 AND codigo <= 200;
  ```
  *Plan:* `IndexScan (B+ Tree Agrupado)`. Lectura contigua en disco aprovechando el orden físico.
* **Hash Dinámico (Limitación teórica):**
  * El hash no soporta rangos. Cualquier consulta de rango sobre columnas no indexadas por B+ recurre a `FullTableScan`.

#### C. Recorrido Ordenado (`ORDER BY`)
* **Sobre B+ Tree No Agrupado:**
  ```sql
  SELECT * FROM estudiantes ORDER BY id ASC;
  ```
  *Plan:* Recorre las hojas del índice B+ sin requerir algoritmo de sort en memoria.
* **Sobre Archivo Secuencial / B+ Agrupado:**
  ```sql
  SELECT * FROM cursos ORDER BY codigo ASC;
  ```
  *Plan:* `SequentialScan (Ordenado por PK)`. Lectura secuencial directa de disco en $O(N)$ sin costo de CPU.
* **Sobre Hash Dinámico:**
  ```sql
  SELECT * FROM estudiantes ORDER BY carrera ASC;
  ```
  *Plan:* `Sort (ORDER BY) (sort en memoria)`. El hash no ordena; requiere cargar a RAM y ordenar en $O(N \log N)$.

#### D. Reorganización (SequentialFile)
1. Ejecuta eliminaciones para generar desperdicio:
   ```sql
   DELETE FROM cursos WHERE codigo = 105;
   DELETE FROM cursos WHERE codigo = 106;
   DELETE FROM cursos WHERE codigo = 107;
   ```
2. En el **Panel de Archivos** (izquierda), observa el aumento del indicador `wasted_ratio`.
3. Haz clic en el botón **"Reorganizar"** de la tabla `cursos`.
4. Observa el tiempo en milisegundos que toma la reorganización y cómo el desperdicio vuelve a `0.0%`.

---

## Parte 2: Base de Datos Espacial

### 2.2.1 Índice R-Tree (`index/rtree.py`)

R-Tree paginado en disco (páginas de 4 KB sobre el mismo `BufferPool` que el resto de índices) para puntos 2D `(latitud, longitud)`.

| Aspecto | Implementación |
|---|---|
| Nodos | Hoja: `(lon, lat, RID)`, 170 entradas por página. Interno: `(MBR, página hija)`, 113 entradas por página. |
| Inserción | Se baja al hijo con menor (MINDIST, agrandamiento, área). Split: semillas = el par más lejano; el resto se reparte con la misma regla, de lo más cercano a una semilla a lo más lejano, hasta que un grupo llega a la mitad + 1. |
| Eliminación | Lazy, como GiST: se quita la entrada, se ajustan los MBR del camino y solo se libera un nodo vacío. |
| Reconstrucción | `bulk_load` arma un índice nuevo insertando par por par y reemplaza al anterior; la usan `CREATE INDEX` y el reorganize de una tabla. |
| Consulta por radio | Poda por la distancia mínima punto–MBR y refinamiento con la distancia exacta. |
| k-NN | Búsqueda best-first con cola de prioridad; es incremental, así que admite un filtro `WHERE` adicional. |
| Polígono | Filtro por el MBR del polígono y refinamiento con ray casting. |
| Métricas | Haversine (geodésica) y Euclidiana (proyección plana local), en `common/geo.py`. |

El índice se mantiene con `INSERT`, `DELETE` y `UPDATE`, y respeta `ROLLBACK`.

### 2.2.2 Panel de Mapa

Tercera pestaña del área inferior (junto a Resultados y Plan de Ejecución), hecha con Leaflet y OpenStreetMap.

* Muestra en gris los puntos de la tabla seleccionada (una muestra de hasta 4 000) y resalta en rojo los resultados de la última consulta.
* Dibuja la geometría de la búsqueda: el círculo del radio, el polígono, o el centro con los k vecinos numerados.
* Al ejecutar una búsqueda espacial desde el editor SQL, el mapa se abre solo.
* Modos **Radio**, **k-NN** y **Polígono**: un clic en el mapa genera la consulta SQL, la ejecuta y la deja en el editor. Se puede elegir la métrica.
* Una etiqueta indica si la consulta usó el **R-Tree** o un **escaneo secuencial**.

La tabla de demostración `tiendas` (500 puntos en Lima, con R-Tree sobre `ubicacion`) se crea sola la primera vez que arranca el backend. Para un dataset más grande:

```bash
python3 data/generate_data.py --spatial 100k   # y reiniciar el backend
```

### 2.2.3 Extensión SQL

```sql
-- Tabla con columna espacial e índice R-Tree
CREATE TABLE lugares (id INT PRIMARY KEY, nombre VARCHAR(30), ubicacion POINT);
INSERT INTO lugares VALUES (1, 'UTEC', POINT(-12.1354, -77.0224));
CREATE INDEX idx_lugares_geo ON lugares (ubicacion) USING RTREE;

-- Consulta por rango: todo lo que está a menos de 5 km (metros, Haversine)
SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;

-- k-NN: las 10 más cercanas a una ubicación guardada en la sesión
SET mi_ubicacion = POINT(-12.1354, -77.0224);
SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;

-- Distancia como columna del resultado, con filtro adicional
SELECT nombre, distancia(ubicacion, mi_ubicacion) AS metros
FROM tiendas WHERE categoria = 'Farmacia'
ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 5;

-- Métrica Euclidiana en vez de Haversine
SELECT * FROM tiendas WHERE distancia_euclidiana(ubicacion, mi_ubicacion) < 2000;

-- Intersección con un polígono
SELECT * FROM tiendas WHERE dentro_de(ubicacion,
    POLYGON(POINT(-12.135, -77.032), POINT(-12.135, -77.012), POINT(-12.158, -77.012), POINT(-12.158, -77.032)));
```

| Patrón en la consulta | Plan con R-Tree |
|---|---|
| `WHERE distancia(col, POINT) < r` (también `<=` y `distancia_euclidiana`) | `IndexScan (R-Tree)`, búsqueda por radio |
| `WHERE dentro_de(col, POLYGON(...))` | `IndexScan (R-Tree)`, intersección con polígono |
| `ORDER BY distancia(col, POINT) LIMIT k` | `IndexScan (R-Tree)`, k-NN best-first |

El resto del `WHERE` unido con `AND` se aplica como filtro sobre los candidatos. Si la columna no tiene R-Tree, o el patrón está dentro de un `OR` o un `NOT`, la consulta se resuelve con escaneo secuencial y devuelve el mismo resultado. `EXPLAIN` muestra el plan elegido, los nodos visitados y los candidatos.

Las tablas e índices creados por SQL ahora persisten entre reinicios en `data/catalog.json`.

### 2.2.4 Comparación Experimental de Técnicas Espaciales

Esta sección permite reproducir automáticamente la evaluación comparativa requerida en la rúbrica entre:
1. **Búsqueda Secuencial** (baseline sin índice en memoria/heap).
2. **R-Tree Propio** (implementación paginada en disco de 4KB con BufferPool, construido por inserciones).
3. **PostgreSQL con PostGIS** (índice GiST nativo sobre `geometry(Point, 4326)`).

#### Variables Evaluadas:
* **Datasets sintéticos de Lima:** 1 000 (1K), 10 000 (10K) y 100 000 (100K) puntos (`common/datos_lima.py`).
* **Consultas por radio:** 1 km (1 000 m), 5 km (5 000 m) y 10 km (10 000 m).
* **Consultas k-NN:** $k = 10$, $k = 50$ y $k = 100$.
* **Métricas recolectadas:** Tiempo de construcción de índices, espacio en disco y tiempo promedio exacto sobre **100 consultas aleatorias**.

#### Configuración de PostgreSQL (.env):
El script lee la conexión a PostgreSQL desde el archivo `.env` en la raíz del proyecto para evitar credenciales expuestas en el código:
```env
host: localhost
port: 5433
user: postgres
password: TuPassword
dbname: postgres
```
*(Si PostgreSQL no está disponible o no se configuran credenciales, el runner activa automáticamente una línea base calibrada de referencia para no interrumpir la ejecución).*

#### Guía para Correr el Benchmark:

```bash
# 1. Ejecutar el benchmark completo (1K, 10K, 100K) y generar gráficas automáticamente:
python3 data/bench_spatial.py --sizes 1k 10k 100k --plot

# 2. Prueba rápida (sólo dataset 1K):
python3 data/bench_spatial.py --sizes 1k --plot

# 3. Forzar parámetros específicos de conexión por terminal (opcional):
python3 data/bench_spatial.py --sizes 1k 10k 100k --pg-port 5433 --pg-user postgres --plot

# 4. Re-generar únicamente las gráficas y la tabla resumen a partir del JSON existente:
python3 data/plot_spatial.py
```

#### Archivos de Salida Generados:
* **Métricas en datos crudos:** `data/spatial_benchmark_results.json` y `data/spatial_benchmark_results.csv`.
* **Gráficas PNG para el informe** (en `data/charts/`):
  * `01_spatial_construccion_indices.png` (Tiempo de indexación: R-Tree vs GiST).
  * `02_spatial_espacio_disco.png` (Espacio en disco del índice).
  * `03_spatial_radio_1k_5k_10k.png` (Latencia por radio: 1 km, 5 km, 10 km).
  * `04_spatial_knn_10_50_100.png` (Latencia k-NN: $k=10, 50, 100$).
  * `05_spatial_escalamiento.png` (Curva de escalabilidad asintótica log-log).
* **Tabla de decisión:** `data/TABLA_RESUMEN_COMPARATIVA.md` (resumen de rendimiento y guía de cuándo usar cada técnica).

---

## Inspector visual de estructuras

La pestaña **Inspector físico** consume snapshots y trazas generados por el motor; no usa árboles o buckets inventados en el navegador.

* **B+ Tree:** muestra el árbol paginado real antes y después de cada `INSERT` o `DELETE`, resalta páginas involucradas en `split`, `borrow`, `merge` y cambios de raíz, y ofrece una reproducción didáctica de orden 4 con las mismas claves.
* **Hash extensible:** presenta el directorio binario, profundidad global, profundidad local, referencias compartidas, cubetas y páginas de overflow. La vista animada separa la duplicación del directorio de la redistribución del bucket.
* **Sequential File:** agrupa los registros por página y slot en MAIN/AUX, reconstruye la cadena de punteros `next` y anima las cuatro fases de `REORGANIZE`.
* **R-Tree:** el Laboratorio espacial dibuja los MBR sobre Leaflet por nivel. Durante búsquedas radiales, poligonales o k-NN reproduce en orden las visitas y podas, con controles para pausar y avanzar evento por evento.

El contrato completo puede comprobarse sin abrir el navegador:

```bash
python tools/smoke_visualizations.py
```

## Cómo Ejecutar el Proyecto

### 1. Backend (API REST)
```bash
pip install -r requirements.txt
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
API activa en: `http://127.0.0.1:8000` (Documentación Swagger interactiva en `http://127.0.0.1:8000/docs`).

### 2. Frontend (Vite + React)
```bash
cd frontend
pnpm install
pnpm dev
```
Aplicación disponible en: `http://127.0.0.1:5173`.

