# Comparación Experimental — Parte 4: Búsqueda Multimedia y Vectorial

## 1. Resultados Cuantitativos (EXACTO vs HNSW vs IVF, $k=10$)

| Dominio | N | Dim | Métrica | Índice | Parámetros | Construcción (s) | Memoria (MB) | Consulta (ms/q) | Speedup | Recall@10 | Origen |
|:---|---:|---:|:---|:---|:---|---:|---:|---:|---:|---:|:---|
| **imagen** | 1,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 1.95 | 0.0787 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 0.0527 | 2.09 | 0.0218 | 3.60x | 0.9760 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `euclidean` | **IVF** | `nlist=32, nprobe=4` | 0.0038 | 2.02 | 0.0232 | 3.40x | 0.9520 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 1.95 | 0.0845 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=16` | 0.0599 | 2.09 | 0.0216 | 3.91x | 0.9550 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **IVF** | `nlist=32, nprobe=16` | 0.0023 | 2.02 | 0.0314 | 2.69x | 0.9910 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 19.53 | 0.6975 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=64` | 0.9477 | 20.91 | 0.0490 | 14.24x | 0.9640 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **IVF** | `nlist=100, nprobe=8` | 0.0246 | 19.80 | 0.1161 | 6.01x | 0.9720 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 19.53 | 0.7179 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 1.2537 | 20.91 | 0.0415 | 17.32x | 0.9490 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **IVF** | `nlist=100, nprobe=16` | 0.0249 | 19.80 | 0.0689 | 10.42x | 0.9490 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 195.31 | 6.9082 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=256` | 24.8400 | 209.08 | 0.4428 | 15.60x | 0.9540 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **IVF** | `nlist=316, nprobe=32` | 0.4266 | 196.70 | 1.0137 | 6.81x | 0.9810 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 195.31 | 6.9394 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=128` | 35.4688 | 209.08 | 0.3125 | 22.20x | 0.9610 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **IVF** | `nlist=316, nprobe=32` | 0.4026 | 196.70 | 0.3643 | 19.05x | 0.9410 | BoVW real (SIFT) |
| **audio** | 1,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 0.98 | 0.0464 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 0.0391 | 1.11 | 0.0140 | 3.33x | 0.9000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `euclidean` | **IVF** | `nlist=32, nprobe=4` | 0.0018 | 1.02 | 0.0158 | 2.93x | 0.8000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 0.98 | 0.0508 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=16` | 0.0493 | 1.11 | 0.0160 | 3.18x | 1.0000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **IVF** | `nlist=32, nprobe=16` | 0.0016 | 1.02 | 0.0210 | 2.41x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 9.77 | 0.2450 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=64` | 0.7440 | 11.14 | 0.0198 | 12.35x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **IVF** | `nlist=100, nprobe=16` | 0.0154 | 9.94 | 0.0912 | 2.68x | 0.9000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 9.77 | 0.3582 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 0.8644 | 11.14 | 0.0199 | 17.99x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **IVF** | `nlist=100, nprobe=16` | 0.0149 | 9.94 | 0.0363 | 9.88x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 97.66 | 2.7118 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 13.5672 | 111.42 | 0.0127 | 213.40x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **IVF** | `nlist=316, nprobe=32` | 0.3011 | 98.73 | 0.4149 | 6.54x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 97.66 | 3.4365 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 14.6503 | 111.42 | 0.0193 | 178.13x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **IVF** | `nlist=316, nprobe=4` | 0.2704 | 98.73 | 0.0316 | 108.66x | 1.0000 | BoAW real (MFCC) |

## 2. Comparación de Índices Vectoriales: Ventajas, Desventajas y Cuándo Usar Cada Uno

| Técnica | Ventajas | Desventajas | Cuándo usarla |
|:---|:---|:---|:---|
| **k-NN Exacto (`EXACTO`)** | Garantiza `Recall@k = 1.000` (exactitud total), construcción instantánea ($O(1)$ al referenciar la matriz) y cero sobrecarga estructural adicional. | Tiempo de consulta lineal $O(N \cdot D)$; la latencia crece proporcionalmente al tamaño de la colección. | Colecciones pequeñas ($N \le 5\text{k}$) o como *ground truth* para calibrar índices aproximados. |
| **IVF (`IndexIVFFlat`)** | Particiona el espacio en `nlist` celdas de Voronoi mediante K-Means; huella de memoria muy compacta (solo añade centroides e IDs de listas invertidas) y construcción rápida. | Si el vector de consulta cae cerca de la frontera entre celdas, requiere un `nprobe` alto para no perder vecinos reales, reduciendo el speedup frente a HNSW. | Colecciones medianas a grandes ($10\text{k} - 1\text{M}$) con presupuesto de RAM ajustado donde un `Recall@10` de $0.90 - 0.96$ es aceptable. |
| **HNSW (`IndexHNSWFlat`)** | Navegación jerárquica en grafos de mundo pequeño; logra el mejor compromiso **latencia sub-milisegundo vs. Recall@10 ($> 0.96$)** en escalas de $10\text{k}$ y $100\text{k}$. | Mayor tiempo de construcción ($O(N \log N)$) y mayor consumo de memoria por almacenar hasta $2 \cdot M$ aristas por vector en la capa base. | Sistemas de recuperación multimedia en tiempo real ($N \ge 10\text{k}$) donde la prioridad es mínima latencia de consulta y alto Recall. |

## 3. Comparación de Métricas de Distancia: Euclidiana vs. Coseno en BoVW / BoAW

| Métrica | Comportamiento sobre Histogramas TF-IDF | Ventajas | Desventajas |
|:---|:---|:---|:---|
| **Distancia Coseno (`cosine`)** | Mide el ángulo entre los vectores TF-IDF normalizados ($1 - \frac{u \cdot v}{\|u\| \|v\|}$), siendo invariante a la cantidad total de keypoints SIFT o tramas MFCC. | Más robusta ante cambios de escala, resolución de imagen o energía global del segmento de audio; preserva la proporción relativa de *visual/audio words*. | Pierde información sobre la riqueza absoluta de texturas (una imagen muy simple y una muy detallada con la misma proporción de palabras visuales dan distancia cercana a 0). |
| **Distancia Euclidiana (`euclidean`)** | Mide la norma $L_2$ ($\|u - v\|_2$) directamente en el espacio de pesos TF-IDF. | Como `tfidf_denso` emplea TF relativo ($\text{tf}/\sum \text{tf}$), funciona bien cuando las imágenes/audios tienen densidades similares de descriptores; soporta cuantización L2 directa en FAISS. | Sensible a diferencias en la norma $L_2$ producidas por vectores muy dispersos frente a vectores concentrados en pocas palabras del codebook. |
