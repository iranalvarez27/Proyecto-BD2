# Minigestor de Base de Datos Multimodal - BD2 (2026-2)

Sistema gestor de base de datos multimodal desarrollado desde cero, que soporta datos relacionales (tablas y almacenamiento físico), espaciales, texto y multimedia.

---

## Estructura del Proyecto

```
Proyecto-BD2/
├── backend/                  # Servidor de API REST (FastAPI) & Capa Fachada
│   ├── catalog.py            # Catálogo de tablas y metadatos de índices
│   ├── engine_adapter.py     # Adaptador que conecta almacenamiento y genera planes
│   └── main.py               # Endpoints REST y CORS
├── common/                   # Tipos comunes y estructuras de bajo nivel
│   ├── page.py               # Slotted Page (4096 bytes)
│   ├── record.py             # Serialización binaria de registros
│   └── types.py              # Definición de tipos de datos, columnas y esquemas
├── storage/                  # Métodos de almacenamiento en disco
│   ├── heap_file.py          # Heap File con Slotted Pages
│   └── sequential_file.py    # Archivo Secuencial Paginado (Main + Aux / Lazy deletion)
├── frontend/                 # Interfaz de Usuario (React + Vite + Tailwind CSS)
│   ├── src/
│   │   ├── components/
│   │   │   ├── FilePanel.jsx     # Panel 1: Archivos, tablas y métricas
│   │   │   ├── QueryPanel.jsx    # Panel 2: Editor de consultas SQL y plantillas
│   │   │   ├── ResultsPanel.jsx  # Panel 3: Grid de resultados y tiempos
│   │   │   └── PlanPanel.jsx     # Panel 4: Árbol visual del Plan de Ejecución
│   │   ├── App.jsx               # Layout principal tipo estudio
│   │   └── index.css
│   └── vite.config.js
└── requirements.txt          # Dependencias Python
```

---

## 2.1.5 Interfaz de Usuario (Los 4 Paneles)

1. **Panel de Archivos (Izquierda):**
   * Inspección de tablas cargadas (`HEAP` y `SEQUENTIAL`).
   * Columnas, tipos de datos (`INT`, `VARCHAR`, etc.) y llaves primarias.
   * Índices activos (B+ Tree, Extendible Hash).
   * Métricas de disco en vivo: conteo de páginas de 4KB, conteo de tuplas y ratio de espacio desperdiciado por eliminación lazy.
   * Botón de **Reorganización** automática cuando el desperdicio supera el 30%.

2. **Panel de Consultas (Superior Centro):**
   * Editor de sentencias SQL multilínea con atajo `Cmd/Ctrl + Enter`.
   * Menú desplegable con plantillas rápidas (`SELECT`, `INSERT`, `ORDER BY`, `TRANSACTIONS`).
   * Botones: **Ejecutar**, **EXPLAIN** (Plan de Ejecución) y Limpiar.
   * Historial de consultas ejecutadas.

3. **Panel de Resultados (Inferior Centro):**
   * Tabla dinámica de resultados con formateo de tipos y números de fila.
   * Indicadores de latencia (`ms`) y número de filas devueltas/afectadas.
   * Exportación instantánea a **CSV** o **JSON**.
   * Detección y visualización amigable de errores.

4. **Panel del Plan de Ejecución (Pestaña dedicada):**
   * Representación visual en árbol de la estrategia del planificador de consultas.
   * Muestra nodos jerárquicos: `SeqScan`, `IndexScan`, `FilterPredicate`, `ExternalSort`, `Projection`.
   * Costos estimados de E/S y conteo de filas estimadas.

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
npm install
npm run dev
```
Aplicación disponible en: `http://127.0.0.1:5173`.