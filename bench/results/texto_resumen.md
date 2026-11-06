# Comparación Experimental — Parte 3: Búsqueda de Texto (Full-Text Search)

## 1. Construcción del Índice y Uso de Disco

> **Nota sobre arquitectura e indexación:** TF-IDF y BM25 son algoritmos de *ranking* y scoring que operan sobre la misma estructura física de índice invertido (`.dict`, `.post`, `.doc`) construida mediante el algoritmo SPIMI en nuestro motor. Por ende, comparten el mismo tiempo de construcción y huella en disco físico frente al índice `GIN` de PostgreSQL.

| N | Índice Invertido | Construcción (s) | Espacio en Disco (MB) | Términos | Postings | Modo |
|---:|:---|---:|---:|---:|---:|:---|
| 1,000 | **SPIMI (Propio)** | 0.234 | 0.90 | 12,876 | 82,534 | SPIMI nativo |
| 1,000 | **GIN (PostgreSQL)** | 0.082 | 1.14 | 12,876 | 82,534 | PostgreSQL real |
| 10,000 | **SPIMI (Propio)** | 1.938 | 7.66 | 49,635 | 856,764 | SPIMI nativo |
| 10,000 | **GIN (PostgreSQL)** | 0.244 | 6.87 | 49,635 | 856,764 | PostgreSQL real |
| 100,000 | **SPIMI (Propio)** | 21.649 | 70.82 | 191,993 | 8,553,973 | SPIMI nativo |
| 100,000 | **GIN (PostgreSQL)** | 2.271 | 49.20 | 191,993 | 8,553,973 | PostgreSQL real |

## 2. Tiempo de Consulta y Relevancia (Precision@10 y Recall@10)

| N | Longitud Consulta | Motor | Latencia Media (ms) | Mediana P50 (ms) | Precision@10 | Recall@10 |
|---:|:---|:---|---:|---:|---:|---:|
| 1,000 | 1 palabra | **TF_IDF** | 0.572 | 0.549 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **BM25** | 0.355 | 0.380 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **GIN** | 0.125 | 0.097 | 0.370 | 0.617 |
| 1,000 | 3 palabras | **TF_IDF** | 1.476 | 1.594 | 0.447 | 0.738 |
| 1,000 | 3 palabras | **BM25** | 1.054 | 1.134 | 0.437 | 0.721 |
| 1,000 | 3 palabras | **GIN** | 0.697 | 0.381 | 0.327 | 0.541 |
| 1,000 | 5+ palabras | **TF_IDF** | 2.312 | 2.298 | 0.507 | 0.844 |
| 1,000 | 5+ palabras | **BM25** | 1.562 | 1.559 | 0.510 | 0.850 |
| 1,000 | 5+ palabras | **GIN** | 1.223 | 1.129 | 0.340 | 0.567 |
| 10,000 | 1 palabra | **TF_IDF** | 0.781 | 0.735 | 0.363 | 0.606 |
| 10,000 | 1 palabra | **BM25** | 0.477 | 0.481 | 0.360 | 0.600 |
| 10,000 | 1 palabra | **GIN** | 0.260 | 0.105 | 0.327 | 0.544 |
| 10,000 | 3 palabras | **TF_IDF** | 2.353 | 2.250 | 0.300 | 0.499 |
| 10,000 | 3 palabras | **BM25** | 1.700 | 1.549 | 0.337 | 0.560 |
| 10,000 | 3 palabras | **GIN** | 1.985 | 1.047 | 0.203 | 0.338 |
| 10,000 | 5+ palabras | **TF_IDF** | 4.133 | 4.043 | 0.357 | 0.594 |
| 10,000 | 5+ palabras | **BM25** | 2.893 | 2.847 | 0.360 | 0.600 |
| 10,000 | 5+ palabras | **GIN** | 6.367 | 2.789 | 0.200 | 0.333 |
| 100,000 | 1 palabra | **TF_IDF** | 1.522 | 1.012 | 0.280 | 0.467 |
| 100,000 | 1 palabra | **BM25** | 0.945 | 0.642 | 0.277 | 0.461 |
| 100,000 | 1 palabra | **GIN** | 2.905 | 0.236 | 0.260 | 0.433 |
| 100,000 | 3 palabras | **TF_IDF** | 9.158 | 6.446 | 0.167 | 0.278 |
| 100,000 | 3 palabras | **BM25** | 7.662 | 5.431 | 0.170 | 0.283 |
| 100,000 | 3 palabras | **GIN** | 15.204 | 2.910 | 0.117 | 0.194 |
| 100,000 | 5+ palabras | **TF_IDF** | 18.311 | 12.802 | 0.143 | 0.239 |
| 100,000 | 5+ palabras | **BM25** | 16.823 | 10.841 | 0.183 | 0.306 |
| 100,000 | 5+ palabras | **GIN** | 36.128 | 17.735 | 0.113 | 0.189 |

## 3. Ventajas, Desventajas y Cuándo Usar Cada Técnica

| Técnica | Ventajas | Desventajas | Cuándo usarla |
|:---|:---|:---|:---|
| **SPIMI + TF-IDF Coseno** | Simple, normaliza por norma euclidiana del documento y pondera rareza global (IDF). | Crece linealmente con la frecuencia del término (sin saturación de TF); documentos cortos con repeticiones pueden dominar. | Consultas cortas o vocabulario técnico donde la presencia repetida de un término exacto es determinante. |
| **SPIMI + BM25** | Saturación no lineal de frecuencia ($k_1$) y penalización calibrada por longitud de documento ($b$). Mejor $P@10$ y $R@10$ en consultas de 3 y 5+ palabras. | Ligero costo aritmético adicional por posting evaluado frente a TF-IDF puro. | Búsqueda general de productos, artículos y documentos de longitud variable (estándar en recuperación de información). |
| **PostgreSQL GIN (`tsvector`)** | Muy veloz en intersecciones booleanas (`@@`) gracias al árbol B+ sobre claves y posting lists comprimidas en C. | `ts_rank_cd` no almacena IDF global en el índice GIN (solo usa frecuencia local y densidad), logrando menor relevancia semántica que BM25 en consultas largas. | Filtrado booleano estricto de palabras clave o cuando los datos ya residen en PostgreSQL transaccional. |
