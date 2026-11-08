#!/usr/bin/env bash
set -uo pipefail
cd /app

if [ -n "${BIBLIOTECA_URL:-}" ]; then
  echo "[arranque] instalando la biblioteca de audio desde BIBLIOTECA_URL"
  python -m deteccion.biblioteca importar "$BIBLIOTECA_URL" \
    || echo "[arranque] AVISO: no se pudo instalar la biblioteca; la API arranca sin ella"
fi

exec python -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
