# Comparación Experimental — Parte 4: Búsqueda Multimedia y Vectorial

## 1. Resultados Cuantitativos (EXACTO vs HNSW vs IVF, $k=10$)

| Dominio | N | Dim | Métrica | Índice | Parámetros | Construcción (s) | Memoria (MB) | Consulta (ms/q) | Speedup | Recall@10 | Origen |
|:---|---:|---:|:---|:---|:---|---:|---:|---:|---:|---:|:---|
| **imagen** | 1,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 1.95 | 0.0057 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 0.0558 | 2.09 | 0.0162 | 0.35x | 0.9460 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `euclidean` | **IVF** | `nlist=32, nprobe=4` | 0.0035 | 2.02 | 0.0213 | 0.27x | 0.9950 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 1.95 | 0.0074 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=16` | 0.0597 | 2.09 | 0.0115 | 0.64x | 0.8250 | BoVW real (SIFT) |
| **imagen** | 1,000 | 512 | `cosine` | **IVF** | `nlist=32, nprobe=16` | 0.0019 | 2.02 | 0.0220 | 0.34x | 0.9770 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 19.53 | 0.1085 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=64` | 0.9461 | 20.91 | 0.0433 | 2.50x | 0.9480 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `euclidean` | **IVF** | `nlist=100, nprobe=8` | 0.0254 | 19.80 | 0.0884 | 1.23x | 0.9550 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 19.53 | 0.1157 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 1.3634 | 20.91 | 0.0388 | 2.98x | 0.9550 | BoVW real (SIFT) |
| **imagen** | 10,000 | 512 | `cosine` | **IVF** | `nlist=100, nprobe=16` | 0.0269 | 19.80 | 0.0647 | 1.79x | 0.9510 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 195.31 | 1.0018 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **HNSW** | `M=16, efC=200, efS=256` | 27.9713 | 209.08 | 0.4495 | 2.23x | 0.9490 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `euclidean` | **IVF** | `nlist=316, nprobe=32` | 0.4353 | 196.70 | 0.9459 | 1.06x | 0.9780 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 195.31 | 1.1064 | 1.00x | 1.0000 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **HNSW** | `M=16, efC=200, efS=128` | 38.6750 | 209.08 | 0.2808 | 3.94x | 0.9660 | BoVW real (SIFT) |
| **imagen** | 100,000 | 512 | `cosine` | **IVF** | `nlist=316, nprobe=32` | 0.4177 | 196.70 | 0.3440 | 3.22x | 0.9540 | BoVW real (SIFT) |
| **audio** | 1,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 0.98 | 0.0051 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 0.0407 | 1.11 | 0.0101 | 0.50x | 0.9600 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `euclidean` | **IVF** | `nlist=32, nprobe=4` | 0.0016 | 1.02 | 0.0081 | 0.63x | 0.9590 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 0.98 | 0.0070 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=16` | 0.0497 | 1.11 | 0.0072 | 0.97x | 0.8640 | BoAW real (MFCC) |
| **audio** | 1,000 | 256 | `cosine` | **IVF** | `nlist=32, nprobe=16` | 0.0017 | 1.02 | 0.0098 | 0.72x | 0.9850 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 9.77 | 0.0869 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=64` | 0.7421 | 11.14 | 0.0266 | 3.27x | 0.9890 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `euclidean` | **IVF** | `nlist=100, nprobe=16` | 0.0148 | 9.94 | 0.0826 | 1.05x | 0.9950 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 9.77 | 0.0970 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 0.8723 | 11.14 | 0.0147 | 6.62x | 0.9890 | BoAW real (MFCC) |
| **audio** | 10,000 | 256 | `cosine` | **IVF** | `nlist=100, nprobe=16` | 0.0145 | 9.94 | 0.0277 | 3.50x | 0.9540 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **EXACTO** | `secuencial` | 0.0000 | 97.66 | 0.5118 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **HNSW** | `M=16, efC=200, efS=32` | 14.6809 | 111.42 | 0.0372 | 13.76x | 0.9590 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `euclidean` | **IVF** | `nlist=316, nprobe=32` | 0.3017 | 98.73 | 0.4078 | 1.26x | 0.9700 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **EXACTO** | `secuencial` | 0.0000 | 97.66 | 0.7890 | 1.00x | 1.0000 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **HNSW** | `M=16, efC=200, efS=32` | 15.6260 | 111.42 | 0.0367 | 21.49x | 0.9710 | BoAW real (MFCC) |
| **audio** | 100,000 | 256 | `cosine` | **IVF** | `nlist=316, nprobe=4` | 0.2800 | 98.73 | 0.0255 | 31.00x | 0.9120 | BoAW real (MFCC) |

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
