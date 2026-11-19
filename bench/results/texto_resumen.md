# Comparación Experimental — Parte 3: Búsqueda de Texto (Full-Text Search)

## 1. Construcción del Índice y Uso de Disco

> **Nota sobre arquitectura e indexación:** TF-IDF y BM25 son algoritmos de *ranking* y scoring que operan sobre la misma estructura física de índice invertido (`.dict`, `.post`, `.doc`) construida mediante el algoritmo SPIMI en nuestro motor. Por ende, comparten el mismo tiempo de construcción y huella en disco físico frente al índice `GIN` de PostgreSQL.

| N | Índice Invertido | Construcción (s) | Espacio en Disco (MB) | Términos | Postings | Modo |
|---:|:---|---:|---:|---:|---:|:---|
| 1,000 | **SPIMI (Propio)** | 0.263 | 0.90 | 12,876 | 82,534 | SPIMI nativo |
| 1,000 | **GIN (PostgreSQL)** | 0.191 | 1.12 | 12,876 | 82,534 | PostgreSQL real |
| 10,000 | **SPIMI (Propio)** | 2.252 | 7.66 | 49,635 | 856,764 | SPIMI nativo |
| 10,000 | **GIN (PostgreSQL)** | 1.563 | 6.69 | 49,635 | 856,764 | PostgreSQL real |
| 100,000 | **SPIMI (Propio)** | 25.481 | 70.82 | 191,993 | 8,553,973 | SPIMI nativo |
| 100,000 | **GIN (PostgreSQL)** | 14.783 | 47.51 | 191,993 | 8,553,973 | PostgreSQL real |

## 2. Tiempo de Consulta y Relevancia (Precision@10 y Recall@10)

| N | Longitud Consulta | Motor | Latencia Media (ms) | Mediana P50 (ms) | Precision@10 | Recall@10 |
|---:|:---|:---|---:|---:|---:|---:|
| 1,000 | 1 palabra | **TF_IDF** | 0.240 | 0.225 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **BM25** | 0.215 | 0.202 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **GIN** | 0.123 | 0.101 | 0.373 | 0.622 |
| 1,000 | 3 palabras | **TF_IDF** | 0.582 | 0.599 | 0.447 | 0.738 |
| 1,000 | 3 palabras | **BM25** | 0.593 | 0.611 | 0.437 | 0.721 |
| 1,000 | 3 palabras | **GIN** | 0.403 | 0.360 | 0.330 | 0.547 |
| 1,000 | 5+ palabras | **TF_IDF** | 0.895 | 0.902 | 0.507 | 0.844 |
| 1,000 | 5+ palabras | **BM25** | 0.906 | 0.892 | 0.510 | 0.850 |
| 1,000 | 5+ palabras | **GIN** | 0.846 | 0.686 | 0.340 | 0.567 |
| 10,000 | 1 palabra | **TF_IDF** | 0.340 | 0.298 | 0.363 | 0.606 |
| 10,000 | 1 palabra | **BM25** | 0.300 | 0.258 | 0.360 | 0.600 |
| 10,000 | 1 palabra | **GIN** | 0.207 | 0.091 | 0.327 | 0.544 |
| 10,000 | 3 palabras | **TF_IDF** | 1.157 | 1.012 | 0.300 | 0.499 |
| 10,000 | 3 palabras | **BM25** | 1.177 | 1.040 | 0.337 | 0.560 |
| 10,000 | 3 palabras | **GIN** | 1.683 | 1.314 | 0.197 | 0.327 |
| 10,000 | 5+ palabras | **TF_IDF** | 2.197 | 1.948 | 0.357 | 0.594 |
| 10,000 | 5+ palabras | **BM25** | 2.068 | 1.987 | 0.360 | 0.600 |
| 10,000 | 5+ palabras | **GIN** | 4.087 | 3.017 | 0.207 | 0.344 |
| 100,000 | 1 palabra | **TF_IDF** | 0.894 | 0.434 | 0.280 | 0.467 |
| 100,000 | 1 palabra | **BM25** | 2.156 | 0.395 | 0.277 | 0.461 |
| 100,000 | 1 palabra | **GIN** | 2.462 | 0.175 | 0.260 | 0.433 |
| 100,000 | 3 palabras | **TF_IDF** | 8.421 | 4.736 | 0.167 | 0.278 |
| 100,000 | 3 palabras | **BM25** | 8.834 | 5.307 | 0.170 | 0.283 |
| 100,000 | 3 palabras | **GIN** | 14.312 | 2.408 | 0.117 | 0.194 |
| 100,000 | 5+ palabras | **TF_IDF** | 17.625 | 9.911 | 0.143 | 0.239 |
| 100,000 | 5+ palabras | **BM25** | 18.594 | 10.576 | 0.183 | 0.306 |
| 100,000 | 5+ palabras | **GIN** | 29.389 | 12.525 | 0.113 | 0.189 |

## 3. Ventajas, Desventajas y Cuándo Usar Cada Técnica

| Técnica | Ventajas | Desventajas | Cuándo usarla |
|:---|:---|:---|:---|
| **SPIMI + TF-IDF Coseno** | Simple, normaliza por norma euclidiana del documento y pondera rareza global (IDF). | Crece linealmente con la frecuencia del término (sin saturación de TF); documentos cortos con repeticiones pueden dominar. | Consultas cortas o vocabulario técnico donde la presencia repetida de un término exacto es determinante. |
| **SPIMI + BM25** | Saturación no lineal de frecuencia ($k_1$) y penalización calibrada por longitud de documento ($b$). Mejor $P@10$ y $R@10$ en consultas de 3 y 5+ palabras. | Ligero costo aritmético adicional por posting evaluado frente a TF-IDF puro. | Búsqueda general de productos, artículos y documentos de longitud variable (estándar en recuperación de información). |
| **PostgreSQL GIN (`tsvector`)** | Muy veloz en intersecciones booleanas (`@@`) gracias al árbol B+ sobre claves y posting lists comprimidas en C. | `ts_rank_cd` no almacena IDF global en el índice GIN (solo usa frecuencia local y densidad), logrando menor relevancia semántica que BM25 en consultas largas. | Filtrado booleano estricto de palabras clave o cuando los datos ya residen en PostgreSQL transaccional. |
