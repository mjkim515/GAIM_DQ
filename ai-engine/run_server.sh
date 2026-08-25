#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8002}"
APP_MODULE="${APP_MODULE:-app.main:app}"
UVICORN_BIN="${UVICORN_BIN:-$SCRIPT_DIR/.venv/bin/uvicorn}"

if [[ ! -x "$UVICORN_BIN" ]]; then
  echo "uvicorn executable not found: $UVICORN_BIN" >&2
  echo "Create the virtualenv and install requirements first." >&2
  exit 1
fi

PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
  echo "Stopping process(es) listening on port $PORT: $PIDS"
  kill $PIDS 2>/dev/null || true
  sleep 1

  REMAINING_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$REMAINING_PIDS" ]]; then
    echo "Force stopping process(es) listening on port $PORT: $REMAINING_PIDS"
    kill -9 $REMAINING_PIDS 2>/dev/null || true
  fi
fi

echo "Starting ai-engine with uvicorn: http://$HOST:$PORT"
exec "$UVICORN_BIN" "$APP_MODULE" --host "$HOST" --port "$PORT"
