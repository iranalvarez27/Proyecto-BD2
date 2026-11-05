# Comparación Experimental — Parte 3: Búsqueda de Texto (Full-Text Search)

## 1. Construcción del Índice y Uso de Disco

> **Nota sobre arquitectura e indexación:** TF-IDF y BM25 son algoritmos de *ranking* y scoring que operan sobre la misma estructura física de índice invertido (`.dict`, `.post`, `.doc`) construida mediante el algoritmo SPIMI en nuestro motor. Por ende, comparten el mismo tiempo de construcción y huella en disco físico frente al índice `GIN` de PostgreSQL.

| N | Índice Invertido | Construcción (s) | Espacio en Disco (MB) | Términos | Postings | Modo |
|---:|:---|---:|---:|---:|---:|:---|
| 1,000 | **SPIMI (Propio)** | 0.255 | 0.90 | 12,876 | 82,534 | SPIMI nativo |
| 1,000 | **GIN (PostgreSQL)** | 0.107 | 0.61 | 12,876 | 82,534 | GIN calibrado (sin Docker) |
| 10,000 | **SPIMI (Propio)** | 2.314 | 7.66 | 49,635 | 856,764 | SPIMI nativo |
| 10,000 | **GIN (PostgreSQL)** | 0.972 | 5.21 | 49,635 | 856,764 | GIN calibrado (sin Docker) |
| 100,000 | **SPIMI (Propio)** | 25.368 | 70.82 | 191,993 | 8,553,973 | SPIMI nativo |
| 100,000 | **GIN (PostgreSQL)** | 10.654 | 48.16 | 191,993 | 8,553,973 | GIN calibrado (sin Docker) |

## 2. Tiempo de Consulta y Relevancia (Precision@10 y Recall@10)

| N | Longitud Consulta | Motor | Latencia Media (ms) | Mediana P50 (ms) | Precision@10 | Recall@10 |
|---:|:---|:---|---:|---:|---:|---:|
| 1,000 | 1 palabra | **TF_IDF** | 0.502 | 0.563 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **BM25** | 0.365 | 0.384 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **GIN** | 0.790 | 0.743 | 0.387 | 0.644 |
| 1,000 | 3 palabras | **TF_IDF** | 1.804 | 1.706 | 0.447 | 0.738 |
| 1,000 | 3 palabras | **BM25** | 1.092 | 1.161 | 0.437 | 0.721 |
| 1,000 | 3 palabras | **GIN** | 1.067 | 1.002 | 0.427 | 0.705 |
| 1,000 | 5+ palabras | **TF_IDF** | 2.482 | 2.513 | 0.507 | 0.844 |
| 1,000 | 5+ palabras | **BM25** | 1.693 | 1.721 | 0.510 | 0.850 |
| 1,000 | 5+ palabras | **GIN** | 1.462 | 1.374 | 0.487 | 0.811 |
| 10,000 | 1 palabra | **TF_IDF** | 0.709 | 0.746 | 0.363 | 0.606 |
| 10,000 | 1 palabra | **BM25** | 0.500 | 0.499 | 0.360 | 0.600 |
| 10,000 | 1 palabra | **GIN** | 0.970 | 0.912 | 0.363 | 0.606 |
| 10,000 | 3 palabras | **TF_IDF** | 2.515 | 2.413 | 0.300 | 0.499 |
| 10,000 | 3 palabras | **BM25** | 1.797 | 1.657 | 0.337 | 0.560 |
| 10,000 | 3 palabras | **GIN** | 1.310 | 1.231 | 0.327 | 0.543 |
| 10,000 | 5+ palabras | **TF_IDF** | 4.319 | 4.181 | 0.357 | 0.594 |
| 10,000 | 5+ palabras | **BM25** | 3.094 | 3.022 | 0.360 | 0.600 |
| 10,000 | 5+ palabras | **GIN** | 1.794 | 1.687 | 0.340 | 0.567 |
| 100,000 | 1 palabra | **TF_IDF** | 1.340 | 0.996 | 0.280 | 0.467 |
| 100,000 | 1 palabra | **BM25** | 1.200 | 0.697 | 0.277 | 0.461 |
| 100,000 | 1 palabra | **GIN** | 1.150 | 1.081 | 0.280 | 0.467 |
| 100,000 | 3 palabras | **TF_IDF** | 11.478 | 7.410 | 0.167 | 0.278 |
| 100,000 | 3 palabras | **BM25** | 9.246 | 5.982 | 0.170 | 0.283 |
| 100,000 | 3 palabras | **GIN** | 1.552 | 1.459 | 0.153 | 0.256 |
| 100,000 | 5+ palabras | **TF_IDF** | 20.945 | 14.390 | 0.143 | 0.239 |
| 100,000 | 5+ palabras | **BM25** | 19.043 | 12.699 | 0.183 | 0.306 |
| 100,000 | 5+ palabras | **GIN** | 2.127 | 2.000 | 0.160 | 0.267 |

## 3. Ventajas, Desventajas y Cuándo Usar Cada Técnica

| Técnica | Ventajas | Desventajas | Cuándo usarla |
|:---|:---|:---|:---|
| **SPIMI + TF-IDF Coseno** | Simple, normaliza por norma euclidiana del documento y pondera rareza global (IDF). | Crece linealmente con la frecuencia del término (sin saturación de TF); documentos cortos con repeticiones pueden dominar. | Consultas cortas o vocabulario técnico donde la presencia repetida de un término exacto es determinante. |
| **SPIMI + BM25** | Saturación no lineal de frecuencia ($k_1$) y penalización calibrada por longitud de documento ($b$). Mejor $P@10$ y $R@10$ en consultas de 3 y 5+ palabras. | Ligero costo aritmético adicional por posting evaluado frente a TF-IDF puro. | Búsqueda general de productos, artículos y documentos de longitud variable (estándar en recuperación de información). |
| **PostgreSQL GIN (`tsvector`)** | Muy veloz en intersecciones booleanas (`@@`) gracias al árbol B+ sobre claves y posting lists comprimidas en C. | `ts_rank_cd` no almacena IDF global en el índice GIN (solo usa frecuencia local y densidad), logrando menor relevancia semántica que BM25 en consultas largas. | Filtrado booleano estricto de palabras clave o cuando los datos ya residen en PostgreSQL transaccional. |
