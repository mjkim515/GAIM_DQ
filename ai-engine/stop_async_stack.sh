#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8002}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_CONTAINER_NAME="${REDIS_CONTAINER_NAME:-gaim-ai-engine-redis}"
DOCKER_BIN="${DOCKER_BIN:-docker}"

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

  pids="$(pgrep -f "celery.*app.workers.celery_app.celery_app" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "No ai-engine Celery worker process found."
    return
  fi

  echo "Stopping ai-engine Celery worker process(es): $pids"
  kill $pids 2>/dev/null || true
  sleep 1

  pids="$(pgrep -f "celery.*app.workers.celery_app.celery_app" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Force stopping ai-engine Celery worker process(es): $pids"
    kill -9 $pids 2>/dev/null || true
  fi
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
echo

stop_celery_workers
stop_port "ai-engine API" "$PORT"
stop_redis_container

echo
echo "ai-engine async stack stop complete."
