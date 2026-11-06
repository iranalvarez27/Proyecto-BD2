# Comparación Experimental — Parte 3: Búsqueda de Texto (Full-Text Search)

## 1. Construcción del Índice y Uso de Disco

> **Nota sobre arquitectura e indexación:** TF-IDF y BM25 son algoritmos de *ranking* y scoring que operan sobre la misma estructura física de índice invertido (`.dict`, `.post`, `.doc`) construida mediante el algoritmo SPIMI en nuestro motor. Por ende, comparten el mismo tiempo de construcción y huella en disco físico frente al índice `GIN` de PostgreSQL.

| N | Índice Invertido | Construcción (s) | Espacio en Disco (MB) | Términos | Postings | Modo |
|---:|:---|---:|---:|---:|---:|:---|
| 1,000 | **SPIMI (Propio)** | 0.244 | 0.90 | 12,879 | 82,538 | SPIMI nativo |
| 1,000 | **GIN (PostgreSQL)** | 0.040 | 1.14 | 12,879 | 82,538 | PostgreSQL real |
| 10,000 | **SPIMI (Propio)** | 2.085 | 7.66 | 49,643 | 856,786 | SPIMI nativo |
| 10,000 | **GIN (PostgreSQL)** | 0.246 | 6.87 | 49,643 | 856,786 | PostgreSQL real |
| 100,000 | **SPIMI (Propio)** | 20.125 | 70.82 | 192,011 | 8,554,203 | SPIMI nativo |
| 100,000 | **GIN (PostgreSQL)** | 2.793 | 49.20 | 192,011 | 8,554,203 | PostgreSQL real |

## 2. Tiempo de Consulta y Relevancia (Precision@10 y Recall@10)

| N | Longitud Consulta | Motor | Latencia Media (ms) | Mediana P50 (ms) | Precision@10 | Recall@10 |
|---:|:---|:---|---:|---:|---:|---:|
| 1,000 | 1 palabra | **TF_IDF** | 0.476 | 0.530 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **BM25** | 0.347 | 0.362 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **GIN** | 0.161 | 0.112 | 0.370 | 0.617 |
| 1,000 | 3 palabras | **TF_IDF** | 1.501 | 1.605 | 0.447 | 0.738 |
| 1,000 | 3 palabras | **BM25** | 1.011 | 1.075 | 0.437 | 0.721 |
| 1,000 | 3 palabras | **GIN** | 0.761 | 0.417 | 0.327 | 0.541 |
| 1,000 | 5+ palabras | **TF_IDF** | 2.292 | 2.288 | 0.507 | 0.844 |
| 1,000 | 5+ palabras | **BM25** | 1.576 | 1.533 | 0.510 | 0.850 |
| 1,000 | 5+ palabras | **GIN** | 1.295 | 1.242 | 0.340 | 0.567 |
| 10,000 | 1 palabra | **TF_IDF** | 0.789 | 0.776 | 0.363 | 0.606 |
| 10,000 | 1 palabra | **BM25** | 0.488 | 0.478 | 0.360 | 0.600 |
| 10,000 | 1 palabra | **GIN** | 0.306 | 0.148 | 0.327 | 0.544 |
| 10,000 | 3 palabras | **TF_IDF** | 2.410 | 2.337 | 0.300 | 0.499 |
| 10,000 | 3 palabras | **BM25** | 1.714 | 1.593 | 0.337 | 0.560 |
| 10,000 | 3 palabras | **GIN** | 2.310 | 1.181 | 0.203 | 0.338 |
| 10,000 | 5+ palabras | **TF_IDF** | 3.989 | 3.979 | 0.357 | 0.594 |
| 10,000 | 5+ palabras | **BM25** | 2.902 | 2.830 | 0.360 | 0.600 |
| 10,000 | 5+ palabras | **GIN** | 7.300 | 3.471 | 0.200 | 0.333 |
| 100,000 | 1 palabra | **TF_IDF** | 1.457 | 1.013 | 0.280 | 0.467 |
| 100,000 | 1 palabra | **BM25** | 1.045 | 0.665 | 0.277 | 0.461 |
| 100,000 | 1 palabra | **GIN** | 2.935 | 0.245 | 0.260 | 0.433 |
| 100,000 | 3 palabras | **TF_IDF** | 8.836 | 6.812 | 0.167 | 0.278 |
| 100,000 | 3 palabras | **BM25** | 7.510 | 5.624 | 0.170 | 0.283 |
| 100,000 | 3 palabras | **GIN** | 17.592 | 3.015 | 0.117 | 0.194 |
| 100,000 | 5+ palabras | **TF_IDF** | 15.264 | 13.671 | 0.143 | 0.239 |
| 100,000 | 5+ palabras | **BM25** | 14.096 | 12.045 | 0.183 | 0.306 |
| 100,000 | 5+ palabras | **GIN** | 37.610 | 18.813 | 0.113 | 0.189 |

## 3. Ventajas, Desventajas y Cuándo Usar Cada Técnica

| Técnica | Ventajas | Desventajas | Cuándo usarla |
|:---|:---|:---|:---|
| **SPIMI + TF-IDF Coseno** | Simple, normaliza por norma euclidiana del documento y pondera rareza global (IDF). | Crece linealmente con la frecuencia del término (sin saturación de TF); documentos cortos con repeticiones pueden dominar. | Consultas cortas o vocabulario técnico donde la presencia repetida de un término exacto es determinante. |
| **SPIMI + BM25** | Saturación no lineal de frecuencia ($k_1$) y penalización calibrada por longitud de documento ($b$). Mejor $P@10$ y $R@10$ en consultas de 3 y 5+ palabras. | Ligero costo aritmético adicional por posting evaluado frente a TF-IDF puro. | Búsqueda general de productos, artículos y documentos de longitud variable (estándar en recuperación de información). |
| **PostgreSQL GIN (`tsvector`)** | Muy veloz en intersecciones booleanas (`@@`) gracias al árbol B+ sobre claves y posting lists comprimidas en C. | `ts_rank_cd` no almacena IDF global en el índice GIN (solo usa frecuencia local y densidad), logrando menor relevancia semántica que BM25 en consultas largas. | Filtrado booleano estricto de palabras clave o cuando los datos ya residen en PostgreSQL transaccional. |
