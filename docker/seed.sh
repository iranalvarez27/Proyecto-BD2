#!/usr/bin/env bash
# Genera los datasets, crea las tablas e índices y (opcionalmente) corre los experimentos.
# Lo ejecuta el servicio "seed" del docker-compose antes de arrancar el backend.
# Es idempotente: si ya se generaron los tamaños pedidos, termina enseguida.
set -uo pipefail
cd /app

SEED="${SEED:-1}"
TAMANOS="${TAMANOS:-1k}"
FMA_VARIANTE="${FMA_VARIANTE:-small}"
CORRER_EXPERIMENTOS="${CORRER_EXPERIMENTOS:-0}"

if [ "$SEED" = "0" ]; then
  echo "[seed] SEED=0: no se generan datasets."
  exit 0
fi

ETIQUETA="$(echo "$TAMANOS" | tr ' ,' '__')"
MARCA="data/.seed_${ETIQUETA}_${FMA_VARIANTE}"
mkdir -p data bench/data bench/results

if [ -f "$MARCA" ] && [ "$CORRER_EXPERIMENTOS" != "1" ]; then
  echo "[seed] Los datasets de tamaño '${TAMANOS}' ya están generados ($MARCA). Nada que hacer."
  exit 0
fi

FALLOS=()
paso () {
  local nombre="$1"; shift
  echo ""
  echo "[seed] ===== ${nombre} ====="
  if "$@"; then
    echo "[seed] OK: ${nombre}"
  else
    echo "[seed] FALLÓ: ${nombre} (se continúa con lo demás)"
    FALLOS+=("$nombre")
  fi
}

if [ ! -f "$MARCA" ]; then
  # shellcheck disable=SC2086  (TAMANOS se separa en palabras a propósito: -n 1k 10k 100k)
  paso "Texto (ESCI)"       python -m bench.datasets.esci       -n $TAMANOS --ingestar
  paso "Imágenes (Amazon)"  python -m bench.datasets.amazon_img -n $TAMANOS --ingestar
  # amazon_img.py termina sin error aunque no pueda descargar ninguna foto: se verifica que haya objetos
  if [ "$(wc -l < bench/data/amazon_img/objetos.csv 2>/dev/null || echo 0)" -le 1 ]; then
    echo "[seed] FALLÓ: Imágenes (Amazon): no se descargó ninguna foto (¿hay internet?)"
    FALLOS+=("Imágenes (Amazon): 0 fotos")
  fi
  paso "Audio (FMA ${FMA_VARIANTE})" python -m bench.datasets.fma --variante "$FMA_VARIANTE" -n $TAMANOS --ingestar
fi

if [ "$CORRER_EXPERIMENTOS" = "1" ]; then
  paso "Experimento vectorial (EXACTO vs HNSW vs IVF)" python -m bench.experiments.vector_compare -n $TAMANOS --plot
  paso "Galería de éxitos y errores"                  python -m bench.experiments.galeria -n 1k
  paso "Experimento de texto (TF-IDF vs BM25 vs GIN)"  python -m bench.experiments.texto -n $TAMANOS --plot
fi

if [ ${#FALLOS[@]} -eq 0 ]; then
  touch "$MARCA"
  echo ""
  echo "[seed] Listo: todo se generó correctamente."
else
  echo ""
  echo "[seed] Terminó con fallos en: ${FALLOS[*]}"
  echo "[seed] La app arranca igual con lo que sí se generó. Revisa los mensajes de arriba y vuelve a correr"
  echo "[seed] 'docker compose up' para reintentar (lo ya descargado o extraído se reutiliza)."
fi
exit 0
