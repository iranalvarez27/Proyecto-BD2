# Comparación Experimental — Parte 3: Búsqueda de Texto (Full-Text Search)

## 1. Construcción del Índice y Uso de Disco

> **Nota sobre arquitectura e indexación:** TF-IDF y BM25 son algoritmos de *ranking* y scoring que operan sobre la misma estructura física de índice invertido (`.dict`, `.post`, `.doc`) construida mediante el algoritmo SPIMI en nuestro motor. Por ende, comparten el mismo tiempo de construcción y huella en disco físico frente al índice `GIN` de PostgreSQL.

| N | Índice Invertido | Construcción (s) | Espacio en Disco (MB) | Términos | Postings | Modo |
|---:|:---|---:|---:|---:|---:|:---|
| 1,000 | **SPIMI (Propio)** | 0.258 | 0.90 | 12,876 | 82,534 | SPIMI nativo |
| 1,000 | **GIN (PostgreSQL)** | 0.237 | 1.12 | 12,876 | 82,534 | PostgreSQL real |
| 10,000 | **SPIMI (Propio)** | 2.254 | 7.66 | 49,635 | 856,764 | SPIMI nativo |
| 10,000 | **GIN (PostgreSQL)** | 1.372 | 6.69 | 49,635 | 856,764 | PostgreSQL real |
| 100,000 | **SPIMI (Propio)** | 24.990 | 70.82 | 191,993 | 8,553,973 | SPIMI nativo |
| 100,000 | **GIN (PostgreSQL)** | 13.541 | 47.51 | 191,993 | 8,553,973 | PostgreSQL real |

## 2. Tiempo de Consulta y Relevancia (Precision@10 y Recall@10)

| N | Longitud Consulta | Motor | Latencia Media (ms) | Mediana P50 (ms) | Precision@10 | Recall@10 |
|---:|:---|:---|---:|---:|---:|---:|
| 1,000 | 1 palabra | **TF_IDF** | 0.211 | 0.198 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **BM25** | 0.211 | 0.198 | 0.387 | 0.644 |
| 1,000 | 1 palabra | **GIN** | 0.117 | 0.104 | 0.373 | 0.622 |
| 1,000 | 3 palabras | **TF_IDF** | 0.568 | 0.587 | 0.447 | 0.738 |
| 1,000 | 3 palabras | **BM25** | 0.577 | 0.599 | 0.437 | 0.721 |
| 1,000 | 3 palabras | **GIN** | 0.247 | 0.220 | 0.307 | 0.506 |
| 1,000 | 5+ palabras | **TF_IDF** | 0.912 | 0.928 | 0.507 | 0.844 |
| 1,000 | 5+ palabras | **BM25** | 0.904 | 0.916 | 0.510 | 0.850 |
| 1,000 | 5+ palabras | **GIN** | 0.433 | 0.332 | 0.440 | 0.733 |
| 10,000 | 1 palabra | **TF_IDF** | 0.310 | 0.269 | 0.363 | 0.606 |
| 10,000 | 1 palabra | **BM25** | 0.299 | 0.258 | 0.360 | 0.600 |
| 10,000 | 1 palabra | **GIN** | 0.122 | 0.104 | 0.337 | 0.561 |
| 10,000 | 3 palabras | **TF_IDF** | 1.139 | 0.975 | 0.300 | 0.499 |
| 10,000 | 3 palabras | **BM25** | 1.142 | 0.992 | 0.337 | 0.560 |
| 10,000 | 3 palabras | **GIN** | 0.402 | 0.332 | 0.227 | 0.376 |
| 10,000 | 5+ palabras | **TF_IDF** | 2.126 | 1.883 | 0.357 | 0.594 |
| 10,000 | 5+ palabras | **BM25** | 2.067 | 1.942 | 0.360 | 0.600 |
| 10,000 | 5+ palabras | **GIN** | 0.806 | 0.402 | 0.307 | 0.511 |
| 100,000 | 1 palabra | **TF_IDF** | 0.828 | 0.416 | 0.280 | 0.467 |
| 100,000 | 1 palabra | **BM25** | 2.219 | 0.389 | 0.277 | 0.461 |
| 100,000 | 1 palabra | **GIN** | 0.737 | 0.166 | 0.267 | 0.444 |
| 100,000 | 3 palabras | **TF_IDF** | 8.642 | 4.995 | 0.167 | 0.278 |
| 100,000 | 3 palabras | **BM25** | 8.732 | 5.085 | 0.170 | 0.283 |
| 100,000 | 3 palabras | **GIN** | 0.774 | 0.401 | 0.117 | 0.194 |
| 100,000 | 5+ palabras | **TF_IDF** | 17.624 | 10.096 | 0.143 | 0.239 |
| 100,000 | 5+ palabras | **BM25** | 18.023 | 10.347 | 0.183 | 0.306 |
| 100,000 | 5+ palabras | **GIN** | 3.889 | 1.047 | 0.147 | 0.244 |

## 3. Ventajas, Desventajas y Cuándo Usar Cada Técnica

| Técnica | Ventajas | Desventajas | Cuándo usarla |
|:---|:---|:---|:---|
| **SPIMI + TF-IDF Coseno** | Simple, normaliza por norma euclidiana del documento y pondera rareza global (IDF). | Crece linealmente con la frecuencia del término (sin saturación de TF); documentos cortos con repeticiones pueden dominar. | Consultas cortas o vocabulario técnico donde la presencia repetida de un término exacto es determinante. |
| **SPIMI + BM25** | Saturación no lineal de frecuencia ($k_1$) y penalización calibrada por longitud de documento ($b$). Mejor $P@10$ y $R@10$ en consultas de 3 y 5+ palabras. | Ligero costo aritmético adicional por posting evaluado frente a TF-IDF puro. | Búsqueda general de productos, artículos y documentos de longitud variable (estándar en recuperación de información). |
| **PostgreSQL GIN (`tsvector`)** | Muy veloz en intersecciones booleanas (`@@`) gracias al árbol B+ sobre claves y posting lists comprimidas en C. | `ts_rank_cd` no almacena IDF global en el índice GIN (solo usa frecuencia local y densidad), logrando menor relevancia semántica que BM25 en consultas largas. | Filtrado booleano estricto de palabras clave o cuando los datos ya residen en PostgreSQL transaccional. |
