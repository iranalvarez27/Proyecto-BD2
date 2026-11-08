# ---------- Imagen de ejecución: motor + API + multimedia + índices vectoriales ----------
FROM python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    NUMBA_CACHE_DIR=/tmp/numba

# libgl1 + libglib2.0-0: OpenCV (SIFT) · libsndfile1 + ffmpeg: lectura de MP3 (librosa / soundfile)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libsndfile1 ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt

# el motor guarda data/ relativo al directorio actual: se ejecuta desde /app
COPY . .
RUN mkdir -p data bench/data bench/results

EXPOSE 8000
CMD ["bash", "docker/arrancar.sh"]

# ---------- Variante para datasets y experimentos ----------
FROM app AS bench
RUN pip install -r requirements-dev.txt psycopg2-binary
CMD ["bash", "docker/seed.sh"]
