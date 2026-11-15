# Galería de Casos de Éxito y Error — Parte 4: Búsqueda Multimedia (k-NN Exacto, $k=5$)

## 1. Resumen de Precisión Cualitativa Top-5 (`euclidean` vs `cosine`)

| Dominio | Colección ($N$) | Consultas Evaluadas | Precisión@5 Media (`euclidean`) | Precisión@5 Media (`cosine`) |
|:---|---:|---:|---:|---:|
| **Imágenes (Amazon SIFT BoVW)** | 1,000 | 50 | 0.100 | 0.108 |
| **Audio (FMA MFCC BoAW)** | 1,000 | 50 | 0.240 | 0.216 |

---

## 2. Galería de Imágenes (Amazon Electronics)

La cuadrícula visual completa se encuentra generada en [`galeria_imagenes.png`](file:///Users/kenzoshibuya/Desktop/Proyecto-BD2/bench/results/galeria_imagenes.png).

### 2.1 Métrica `euclidean` — Imágenes

- **Caso de Éxito (4/5 aciertos):** Consulta `ID 2054` — Categoría **`Computer Components`** (*ASUS Dual NVIDIA GeForce RTX 3070 Gaming Graphics Card (PCIe 4.0, 8GB…*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `82460` | `Computer Components` | ASUS GeForce GTX 1650 4GB Phoenix Fan Overclocked Edit… | 0.0280 | Sí |
| #2 | `78347` | `Computer Components` | EVGA 256-P2-N751-TR e-GeForce 8600 GT 256 MB PCI-Expre… | 0.0333 | Sí |
| #3 | `93123` | `Computer Components` | ASUS TUF Gaming B450M-PLUS II AMD AM4 (Ryzen 5000, 3rd… | 0.0341 | Sí |
| #4 | `78344` | `Computer Components` | ASUS P8H67-M PRO/CSM (REV 3.0) LGA 1155 Intel H67 HDMI… | 0.0342 | Sí |
| #5 | `22184` | `Binoculars & Scopes` | Nikon Aculon A211 10x50 Binoculars Black (8248) Bundle… | 0.0342 | No |

- **Caso de Error (0/5 aciertos):** Consulta `ID 99007` — Categoría **`MP3 & MP4 Player Accessories`** (*iPod Touch 4 Case, Bastex Hybrid Slim Fit Black Rubber Silicone Cover…*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `93873` | `Bags & Cases` | Lekufee Small Waterproof Carrying Case for DJI Osmo Ac… | 0.0319 | No |
| #2 | `43444` | `Video` | Video Camera Camcorder 4K, 48MP 30FPS with IR Night Ve… | 0.0338 | No |
| #3 | `34556` | `Car Electronics` | Dash Cam Front and Rear with WiFi, 2.5K Front & 1080P … | 0.0343 | No |
| #4 | `21238` | `Film Photography` | Alteagle 160 Pockets Mini Photo Album, Kpop Photocard … | 0.0354 | No |
| #5 | `88418` | `AC Adapters` | New AC Adapter Power Charger&US Cord for Dell 05U092 0… | 0.0356 | No |

### 2.2 Métrica `cosine` — Imágenes

- **Caso de Éxito (4/5 aciertos):** Consulta `ID 65122` — Categoría **`Computer Accessories & Peripherals`** (*Compact Wireless Keyboard Mouse, 2.4GHz Ultra Thin Small Wireless Key…*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `90828` | `Computer Accessories & Peripherals` | Wireless Keyboard and Mouse Combo, E-YOOSO 2.4G Full-S… | 0.2997 | Sí |
| #2 | `82499` | `Office Electronics Accessories` | Brother Home and Office Labeler (PT-D200SA) with Bonus… | 0.3536 | No |
| #3 | `32132` | `Computer Accessories & Peripherals` | Nuklz N Magnus 325 | Wireless Large Print Full Size Co… | 0.3791 | Sí |
| #4 | `19689` | `Computer Accessories & Peripherals` | Keyboard Cover for 15.6" Lenovo ThinkPad E15 Gen 4 3 2… | 0.4692 | Sí |
| #5 | `92855` | `Computer Accessories & Peripherals` | YMDK 129 Key Autumn ZDA Similar to XDA Keycaps PBT Dye… | 0.4999 | Sí |

- **Caso de Error (0/5 aciertos):** Consulta `ID 142` — Categoría **`Battery Testers`** (*Yakamoz Universal Battery Tester Hand Held Battery Checker Household …*)

| Rank | ID Vecino | Categoría Recuperada | Título | Distancia | ¿Coincide? |
|---:|---:|:---|:---|---:|:---:|
| #1 | `79161` | `Computers & Tablets` | Lenovo ThinkCentre M72e 4004H1U Desktop Computer Windo… | 0.2022 | No |
| #2 | `43644` | `Accessories` | StickerTalk Vehicle Is Equipped with Recording Devices… | 0.3885 | No |
| #3 | `1533` | `Computer Accessories & Peripherals` | Sony Media Memory Stick Duo Replacement Adaptor (MSAC-… | 0.4052 | No |
| #4 | `1319` | `Lighting & Studio` | Aputure Amaran MC RGBWW Mini On Camera Video Light,320… | 0.4153 | No |
| #5 | `67441` | `Adapters` | Maxell Hp21 Headphone and Cell Adapter Kit (190398) | 0.4645 | No |

### Explicación Técnica de los Casos de Error en Imágenes (BoVW SIFT)
1. **Pérdida de geometría global (Bag-of-Words sin verificación espacial):** El histograma BoVW cuantiza parches locales de gradiente SIFT de $128\text{D}$ ignorando dónde aparecen en la imagen. Por ello, objetos rectangulares oscuros sobre fondo blanco (p. ej., un disco duro externo, una batería portátil, un estuche o una tarjeta capturadora) comparten las mismas esquinas y bordes de alto contraste, activando las mismas *visual words* aunque pertenezcan a subcategorías distintas.
2. **Invarianza al color (escala de grises):** SIFT opera sobre luminancia; dos productos con idéntica textura metálica o malla (como un micrófono y un parlante Bluetooth) generan descriptores locales casi indistinguibles.

---

## 3. Galería de Audio (FMA — Segmentos de 2.0 s con MFCC BoAW)

### 3.1 Métrica `euclidean` — Audio

- **Caso de Éxito (5/5 aciertos):** Pista `114541` seg `11` (`22.0-24.0s`) — Género **`Instrumental`** (*Liquor Files - Treacle* — Blue Dot Sessions)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `114238` | `3` | `6.0-8.0s` | `Instrumental` | Grand Caravan — Blue Dot Sessions | 0.3968 | Sí |
| #2 | `115473` | `4` | `8.0-10.0s` | `Instrumental` | Farsical - The PI Sleeps — Blue Dot Sessions | 0.4708 | Sí |
| #3 | `93915` | `0` | `0.0-2.0s` | `Instrumental` | Downtown Serenade — Jahzzar | 0.4730 | Sí |
| #4 | `115473` | `12` | `24.0-26.0s` | `Instrumental` | Farsical - The PI Sleeps — Blue Dot Sessions | 0.5182 | Sí |
| #5 | `115473` | `2` | `4.0-6.0s` | `Instrumental` | Farsical - The PI Sleeps — Blue Dot Sessions | 0.5289 | Sí |

- **Caso de Error (0/5 aciertos):** Pista `126292` seg `12` (`24.0-26.0s`) — Género **`Electronic`** (*Universal Warrior (Special Edition)* — Gorowski)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `123866` | `14` | `28.0-30.0s` | `Rock` | Nasty Boots — The Barreracudas | 0.1930 | No |
| #2 | `19760` | `0` | `0.0-2.0s` | `Pop` | Fish in the Sea — Dirty Mittens | 0.2094 | No |
| #3 | `1649` | `7` | `14.0-16.0s` | `Pop` | Inis Meain — So Cow | 0.2131 | No |
| #4 | `149103` | `10` | `20.0-22.0s` | `Pop` | Explosions — Coco Morier | 0.2145 | No |
| #5 | `149103` | `5` | `10.0-12.0s` | `Pop` | Explosions — Coco Morier | 0.2189 | No |

### 3.2 Métrica `cosine` — Audio

- **Caso de Éxito (5/5 aciertos):** Pista `114541` seg `11` (`22.0-24.0s`) — Género **`Instrumental`** (*Liquor Files - Treacle* — Blue Dot Sessions)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `114238` | `3` | `6.0-8.0s` | `Instrumental` | Grand Caravan — Blue Dot Sessions | 0.1243 | Sí |
| #2 | `115473` | `4` | `8.0-10.0s` | `Instrumental` | Farsical - The PI Sleeps — Blue Dot Sessions | 0.1971 | Sí |
| #3 | `93915` | `0` | `0.0-2.0s` | `Instrumental` | Downtown Serenade — Jahzzar | 0.2112 | Sí |
| #4 | `115473` | `12` | `24.0-26.0s` | `Instrumental` | Farsical - The PI Sleeps — Blue Dot Sessions | 0.2602 | Sí |
| #5 | `115473` | `2` | `4.0-6.0s` | `Instrumental` | Farsical - The PI Sleeps — Blue Dot Sessions | 0.2735 | Sí |

- **Caso de Error (0/5 aciertos):** Pista `68538` seg `0` (`0.0-2.0s`) — Género **`Experimental`** (*Crowd Long* — Audionautics)

| Rank | Track ID | Segmento | Ventana (s) | Género Recuperado | Canción — Artista | Distancia | ¿Coincide? |
|---:|---:|---:|:---:|:---|:---|---:|:---:|
| #1 | `94415` | `10` | `20.0-22.0s` | `Electronic` | Somatou — Kakurenbo | 0.0584 | No |
| #2 | `53589` | `0` | `0.0-2.0s` | `Folk` | Keening — Big Blood | 0.1009 | No |
| #3 | `53589` | `1` | `2.0-4.0s` | `Folk` | Keening — Big Blood | 0.1022 | No |
| #4 | `108808` | `2` | `4.0-6.0s` | `Hip-Hop` | The Trap — D3Zs | 0.1289 | No |
| #5 | `73340` | `8` | `16.0-18.0s` | `Electronic` | Forecast — Büromaschinen | 0.1778 | No |

### Explicación Técnica de los Casos de Error en Audio (BoAW MFCC)
1. **Similitud tímbrica instantánea entre géneros distintos:** Los coeficientes MFCC ($c_1 \dots c_{19}$) describen la envolvente espectral de corto plazo (timbre/instrumentación en ventanas de ~93 ms). Cuando un segmento de 2 segundos contiene solo una introducción acústica, un pasaje vocal o percusión aislada, una pista de *Folk*, *Pop* o *Indie-Rock* presenta la misma huella espectral.
2. **Ausencia de orden temporal y BPM en el histograma:** El modelo Bag-of-Audio-Words resume las 87 tramas del segmento de 2 s en un histograma estático de frecuencias de *audio words*, excelente para identificar fragmentos de la misma grabación (detección de copyright) o texturas instrumentales densas, pero ciego a la progresión armónica de largo plazo.
