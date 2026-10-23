#!/bin/sh
set -eu

: "${UVICORN_HOST:?UVICORN_HOST must be set to the WireGuard interface IP}"
UVICORN_PORT="${UVICORN_PORT:-8000}"

exec uvicorn dia_run.web.app:app --host "$UVICORN_HOST" --port "$UVICORN_PORT" --no-proxy-headers
