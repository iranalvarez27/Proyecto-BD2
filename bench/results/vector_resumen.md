# Comparación Experimental — Parte 4: Búsqueda Multimedia y Vectorial

## 1. Resultados Cuantitativos (EXACTO vs HNSW vs IVF, $k=10$)

| Dominio | N | Dim | Métrica | Índice | Parámetros | Construcción (s) | Memoria (MB) | Consulta (ms/q) | Speedup | Recall@10 | Origen |
|:---|---:|---:|:---|:---|:---|---:|---:|---:|---:|---:|:---|
| **imagen** | 1,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 1.95 | 0.0769 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 0.0587 | 2.09 | 0.0233 | 3.31x | 0.9760 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `euclidean` | **IVF** | `nlist=32, nprobe=4` | 0.0031 | 2.02 | 0.0272 | 2.83x | 0.9770 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 1.95 | 0.0832 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=16` | 0.0602 | 2.09 | 0.0218 | 3.82x | 0.9600 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **IVF** | `nlist=32, nprobe=16` | 0.0025 | 2.02 | 0.0325 | 2.56x | 0.9840 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 19.53 | 0.7231 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=64` | 1.0059 | 20.91 | 0.0533 | 13.56x | 0.9630 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **IVF** | `nlist=100, nprobe=8` | 0.0239 | 19.80 | 0.1197 | 6.04x | 0.9600 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 19.53 | 0.7047 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 1.3303 | 20.91 | 0.0546 | 12.90x | 0.9560 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **IVF** | `nlist=100, nprobe=16` | 0.0259 | 19.80 | 0.0705 | 9.99x | 0.9470 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 195.31 | 7.2956 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=256` | 28.6906 | 209.08 | 0.4922 | 14.82x | 0.9530 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **IVF** | `nlist=316, nprobe=32` | 0.4602 | 196.70 | 1.1315 | 6.45x | 0.9790 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 195.31 | 7.1018 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=128` | 39.7616 | 209.08 | 0.3227 | 22.01x | 0.9700 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **IVF** | `nlist=316, nprobe=32` | 0.4939 | 196.70 | 0.3822 | 18.58x | 0.9340 | BoVW real (SIFT) |
| **audio** | 1,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 0.98 | 0.0440 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 0.0417 | 1.11 | 0.0173 | 2.55x | 0.9630 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `euclidean` | **IVF** | `nlist=32, nprobe=4` | 0.0019 | 1.02 | 0.0144 | 3.05x | 0.9630 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 0.98 | 0.0437 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=16` | 0.0497 | 1.11 | 0.0173 | 2.53x | 0.9670 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **IVF** | `nlist=32, nprobe=16` | 0.0017 | 1.02 | 0.0210 | 2.08x | 0.9980 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 9.77 | 0.2986 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=64` | 0.7605 | 11.14 | 0.0347 | 8.61x | 0.9800 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **IVF** | `nlist=100, nprobe=16` | 0.0175 | 9.94 | 0.0898 | 3.33x | 0.9780 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 9.77 | 0.2930 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 0.9015 | 11.14 | 0.0278 | 10.55x | 0.9940 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **IVF** | `nlist=100, nprobe=16` | 0.0151 | 9.94 | 0.0390 | 7.52x | 0.9560 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 97.66 | 3.0932 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 16.5424 | 111.42 | 0.0495 | 62.46x | 0.9640 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **IVF** | `nlist=316, nprobe=32` | 0.3260 | 98.73 | 0.4358 | 7.10x | 0.9880 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 97.66 | 3.2561 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 16.6159 | 111.42 | 0.0471 | 69.10x | 0.9810 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **IVF** | `nlist=316, nprobe=4` | 0.3127 | 98.73 | 0.0369 | 88.20x | 0.9500 | BoAW real (MFCC) |

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
