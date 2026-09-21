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
│   └── key_codec.py          # Codificación de claves binarias
├── query/                    # Motor de Consultas SQL
│   ├── lexer.py / tokens.py  # Analizador léxico
│   ├── parser.py / ast.py    # Analizador sintáctico y AST
│   ├── catalog.py            # Catálogo unificado de tablas e índices
│   └── conexion.py           # Planificador y ejecutor de consultas
├── data/                     # Archivos de datos (.bin, .idx)
│   └── generate_data.py      # Generador de datasets para benchmarks (1K, 10K, 100K)
├── frontend/                 # Interfaz de Usuario (React + Vite + Tailwind CSS)
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