# Galería de Casos de Éxito y Error — Parte 4: Búsqueda Multimedia (k-NN Exacto, $k=5$)

## 1. Resumen de Precisión Cualitativa Top-5 (`euclidean` vs `cosine`)

| Dominio | Colección ($N$) | Consultas Evaluadas | Precisión@5 Media (`euclidean`) | Precisión@5 Media (`cosine`) |
|:---|---:|---:|---:|---:|
| **Imágenes (Amazon SIFT BoVW)** | 1,000 | 50 | 0.132 | 0.144 |
| **Audio (FMA MFCC BoAW)** | 1,000 | 50 | 0.244 | 0.280 |

---

## 2. Galería de Imágenes (Amazon Electronics)

La cuadrícula visual completa se encuentra generada en [`galeria_imagenes.png`](file:///Users/kenzoshibuya/Desktop/Proyecto-BD2/bench/results/galeria_imagenes.png).

### 2.1 Métrica `euclidean` — Imágenes

- **Caso de Éxito (4/5 aciertos):** Consulta `ID 259` — Categoría **`Laptop Accessories`** (*Temark New A1382 Battery for MacBook Pro 15 inch A1286 (only for Earl…*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `235` | `Laptop Accessories` | 48W New PA3817U-1BRS PA3819U-1BRS Battery for Toshiba … | 0.0440 | Sí |
| #2 | `315` | `Laptop Accessories` | New GHU 90W 4.62A 7.4mm Tip AC Adapter Charger Compati… | 0.0443 | Sí |
| #3 | `188` | `Laptop Accessories` | Laptop VS03XL 849313-850 Battery for HP Envy 15T-AS000… | 0.0473 | Sí |
| #4 | `767` | `Tablet Replacement Parts` | SWARK Replacement Battery MLP29110109 Compatible with … | 0.0480 | No |
| #5 | `1051` | `Laptop Accessories` | 19.5V 3.33A 65W Replacement AC Power Adapter Charger f… | 0.0506 | Sí |

- **Caso de Error (0/5 aciertos):** Consulta `ID 982` — Categoría **`CB & Two-Way Radios`** (*CD-58 Rapid Charger Compatible for Radio VX231 VX260 VX261 VX264 VX45…*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `915` | `Computers` | hBARSCI Eyes Vinyl Decal - 5 Inches - for Cars, Trucks… | 0.0295 | No |
| #2 | `479` | `Accessories` | Acelevel Premium 3Amp Power Adapter with 4 Way Splitte… | 0.0298 | No |
| #3 | `106` | `All Electronics` | OwlTree Upgraded New 2022 Protective Case for Steam De… | 0.0307 | No |
| #4 | `25` | `Tablet Accessories` | HQRP AC Adapter Compatible with Western Digital WD My … | 0.0307 | No |
| #5 | `258` | `AC Adapters` | 12V Power Supply 7A 84W Security System Power Adapter,… | 0.0308 | No |

### 2.2 Métrica `cosine` — Imágenes

- **Caso de Éxito (5/5 aciertos):** Consulta `ID 259` — Categoría **`Laptop Accessories`** (*Temark New A1382 Battery for MacBook Pro 15 inch A1286 (only for Earl…*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `235` | `Laptop Accessories` | 48W New PA3817U-1BRS PA3819U-1BRS Battery for Toshiba … | 0.2252 | Sí |
| #2 | `315` | `Laptop Accessories` | New GHU 90W 4.62A 7.4mm Tip AC Adapter Charger Compati… | 0.2914 | Sí |
| #3 | `42` | `Laptop Accessories` | Laptop Battery for Toshiba Qosmio X500 X505 Satellite … | 0.3088 | Sí |
| #4 | `1051` | `Laptop Accessories` | 19.5V 3.33A 65W Replacement AC Power Adapter Charger f… | 0.3185 | Sí |
| #5 | `188` | `Laptop Accessories` | Laptop VS03XL 849313-850 Battery for HP Envy 15T-AS000… | 0.3525 | Sí |

- **Caso de Error (0/5 aciertos):** Consulta `ID 632` — Categoría **`Adapters`** (*Dongle Dangler 3.5mm Headphone Jack Adapter - Works with iPhone -14/1…*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `1078` | `Computer Components` | Lee_Store New CPU Cooling Fan with Copper core Heatsin… | 0.1729 | No |
| #2 | `244` | `All Electronics` | Josi Minea x 2 Pcs 2.5mm Male to 3.5mm Female Audio Ad… | 0.3109 | No |
| #3 | `1090` | `Lighting & Studio` | Funny Whole Llama Fun - Llama Fiesta Baby Shower or Bi… | 0.3247 | No |
| #4 | `456` | `Computers & Tablets` | SkyTech Archangel 3.0 Gaming Computer PC Desktop - Ryz… | 0.3463 | No |
| #5 | `841` | `AC Adapters` | PERFEIDY 9V 1A 0.8A 0.5A Charger 9.0V 1.0A AC Adapter … | 0.4023 | No |

### Explicación Técnica de los Casos de Error en Imágenes (BoVW SIFT)
1. **Pérdida de geometría global (Bag-of-Words sin verificación espacial):** El histograma BoVW cuantiza parches locales de gradiente SIFT de $128\text{D}$ ignorando dónde aparecen en la imagen. Por ello, objetos rectangulares oscuros sobre fondo blanco (p. ej., un disco duro externo, una batería portátil, un estuche o una tarjeta capturadora) comparten las mismas esquinas y bordes de alto contraste, activando las mismas *visual words* aunque pertenezcan a subcategorías distintas.
2. **Invarianza al color (escala de grises):** SIFT opera sobre luminancia; dos productos con idéntica textura metálica o malla (como un micrófono y un parlante Bluetooth) generan descriptores locales casi indistinguibles.

---

## 3. Galería de Audio (FMA — Segmentos de 2.0 s con MFCC BoAW)

### 3.1 Métrica `euclidean` — Audio

- **Caso de Éxito (5/5 aciertos):** Pista `149103` seg `4` (`8.0-10.0s`) — Género **`Pop`** (*Explosions* — Coco Morier)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `58117` | `10` | `20.0-22.0s` | `Pop` | The Painting I Made — The Golden Hours | 0.2763 | Sí |
| #2 | `58117` | `13` | `26.0-28.0s` | `Pop` | The Painting I Made — The Golden Hours | 0.2932 | Sí |
| #3 | `58117` | `5` | `10.0-12.0s` | `Pop` | The Painting I Made — The Golden Hours | 0.3508 | Sí |
| #4 | `58117` | `7` | `14.0-16.0s` | `Pop` | The Painting I Made — The Golden Hours | 0.3876 | Sí |
| #5 | `58117` | `4` | `8.0-10.0s` | `Pop` | The Painting I Made — The Golden Hours | 0.4122 | Sí |

- **Caso de Error (0/5 aciertos):** Pista `64787` seg `8` (`16.0-18.0s`) — Género **`Pop`** (*Beastly* — Invisible Sports)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `137484` | `7` | `14.0-16.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.1716 | No |
| #2 | `140625` | `11` | `22.0-24.0s` | `Hip-Hop` | Back To It (12inchstrumental) — The Impossebulls | 0.3574 | No |
| #3 | `137484` | `10` | `20.0-22.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.4342 | No |
| #4 | `137484` | `8` | `16.0-18.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.5146 | No |
| #5 | `137484` | `6` | `12.0-14.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.5701 | No |

### 3.2 Métrica `cosine` — Audio

- **Caso de Éxito (5/5 aciertos):** Pista `125237` seg `5` (`10.0-12.0s`) — Género **`Experimental`** (*Teo* — Derek Baron)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `91130` | `1` | `2.0-4.0s` | `Experimental` | Foundation Of Pain Management — Chuck Bettis & Joe Merol… | 0.0800 | Sí |
| #2 | `91130` | `0` | `0.0-2.0s` | `Experimental` | Foundation Of Pain Management — Chuck Bettis & Joe Merol… | 0.0804 | Sí |
| #3 | `91130` | `2` | `4.0-6.0s` | `Experimental` | Foundation Of Pain Management — Chuck Bettis & Joe Merol… | 0.1314 | Sí |
| #4 | `91130` | `5` | `10.0-12.0s` | `Experimental` | Foundation Of Pain Management — Chuck Bettis & Joe Merol… | 0.1376 | Sí |
| #5 | `91130` | `6` | `12.0-14.0s` | `Experimental` | Foundation Of Pain Management — Chuck Bettis & Joe Merol… | 0.2989 | Sí |

- **Caso de Error (0/5 aciertos):** Pista `64787` seg `8` (`16.0-18.0s`) — Género **`Pop`** (*Beastly* — Invisible Sports)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `137484` | `8` | `16.0-18.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.0097 | No |
| #2 | `137484` | `9` | `18.0-20.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.0105 | No |
| #3 | `137484` | `7` | `14.0-16.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.0191 | No |
| #4 | `140625` | `11` | `22.0-24.0s` | `Hip-Hop` | Back To It (12inchstrumental) — The Impossebulls | 0.0875 | No |
| #5 | `137484` | `10` | `20.0-22.0s` | `Experimental` | An Egg In The Piano Lost In The Bo… — Zreen Toyz | 0.1509 | No |

### Explicación Técnica de los Casos de Error en Audio (BoAW MFCC)
1. **Similitud tímbrica instantánea entre géneros distintos:** Los coeficientes MFCC ($c_1 \dots c_{19}$) describen la envolvente espectral de corto plazo (timbre/instrumentación en ventanas de ~93 ms). Cuando un segmento de 2 segundos contiene solo una introducción acústica, un pasaje vocal o percusión aislada, una pista de *Folk*, *Pop* o *Indie-Rock* presenta la misma huella espectral.
2. **Ausencia de orden temporal y BPM en el histograma:** El modelo Bag-of-Audio-Words resume las 87 tramas del segmento de 2 s en un histograma estático de frecuencias de *audio words*, excelente para identificar fragmentos de la misma grabación (detección de copyright) o texturas instrumentales densas, pero ciego a la progresión armónica de largo plazo.
