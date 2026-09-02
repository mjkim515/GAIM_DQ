#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8002}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_CONTAINER_NAME="${REDIS_CONTAINER_NAME:-gaim-ai-engine-redis}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
CELERY_BIN="${CELERY_BIN:-$SCRIPT_DIR/.venv/bin/celery}"
CELERY_APP="${CELERY_APP:-app.workers.celery_app.celery_app}"
CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:$REDIS_PORT/0}"
CELERY_WORKER_PATTERN="${CELERY_WORKER_PATTERN:-celery.*app.workers.celery_app.celery_app}"

print_celery_processes() {
  local label="$1"
  local pids

  echo "$label"
  pids="$(pgrep -f "$CELERY_WORKER_PATTERN" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "  No ai-engine Celery worker process found."
    return
  fi

  ps -p "$(echo "$pids" | paste -sd, -)" -o pid,lstart,command 2>/dev/null || true
}

inspect_celery_workers() {
  local label="$1"

  echo "$label"
  if [[ ! -x "$CELERY_BIN" ]]; then
    echo "  Celery executable not found: $CELERY_BIN"
    return
  fi

  if ! CELERY_BROKER_URL="$CELERY_BROKER_URL" "$CELERY_BIN" -A "$CELERY_APP" inspect ping; then
    echo "  No Celery worker response, or broker is unavailable."
  fi
}

stop_port() {
  local name="$1"
  local port="$2"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "$name is not listening on port $port."
    return
  fi

  echo "Stopping $name process(es) on port $port: $pids"
  kill $pids 2>/dev/null || true
  sleep 1

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Force stopping $name process(es) on port $port: $pids"
    kill -9 $pids 2>/dev/null || true
  fi
}

stop_celery_workers() {
  local pids

  print_celery_processes "Celery worker processes before stop:"

  pids="$(pgrep -f "$CELERY_WORKER_PATTERN" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return
  fi

  echo "Stopping ai-engine Celery worker process(es): $pids"
  kill $pids 2>/dev/null || true
  sleep 1

  pids="$(pgrep -f "$CELERY_WORKER_PATTERN" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Force stopping ai-engine Celery worker process(es): $pids"
    kill -9 $pids 2>/dev/null || true
  fi

  print_celery_processes "Celery worker processes after stop:"
}

stop_redis_container() {
  if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
    echo "Docker not found. Skipping Redis container stop."
    return
  fi

  if "$DOCKER_BIN" ps --format '{{.Names}}' | grep -qx "$REDIS_CONTAINER_NAME"; then
    echo "Stopping Redis container: $REDIS_CONTAINER_NAME"
    "$DOCKER_BIN" stop "$REDIS_CONTAINER_NAME" >/dev/null
    return
  fi

  echo "Redis container is not running: $REDIS_CONTAINER_NAME"
}

echo "Stopping ai-engine async stack"
echo "  api port  : $HOST:$PORT"
echo "  redis port: $REDIS_PORT"
echo "  broker    : $CELERY_BROKER_URL"
echo

inspect_celery_workers "Celery inspect ping before stop:"
stop_celery_workers
stop_port "ai-engine API" "$PORT"
stop_redis_container
inspect_celery_workers "Celery inspect ping after stop:"

echo
echo "ai-engine async stack stop complete."
