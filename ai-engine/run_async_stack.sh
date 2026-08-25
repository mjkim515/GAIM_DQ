#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8002}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_URL="${REDIS_URL:-redis://$REDIS_HOST:$REDIS_PORT/0}"
CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://$REDIS_HOST:$REDIS_PORT/1}"
CELERY_WORKER_CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-3}"

PIDS=()

cleanup() {
  local pid

  if [[ ${#PIDS[@]} -eq 0 ]]; then
    return
  fi

  echo
  echo "Stopping ai-engine async stack..."
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}

start_service() {
  local name="$1"
  shift

  echo "Starting $name..."
  (
    "$@" 2>&1 | sed "s/^/[$name] /"
  ) &
  PIDS+=("$!")
}

run_redis() {
  cd "$SCRIPT_DIR"
  REDIS_HOST="$REDIS_HOST" REDIS_PORT="$REDIS_PORT" ./run_redis.sh
}

run_api() {
  cd "$SCRIPT_DIR"
  HOST="$HOST" \
    PORT="$PORT" \
    REDIS_URL="$REDIS_URL" \
    CELERY_BROKER_URL="$CELERY_BROKER_URL" \
    CELERY_RESULT_BACKEND="$CELERY_RESULT_BACKEND" \
    ./run_server.sh
}

run_worker() {
  cd "$SCRIPT_DIR"
  REDIS_URL="$REDIS_URL" \
    CELERY_BROKER_URL="$CELERY_BROKER_URL" \
    CELERY_RESULT_BACKEND="$CELERY_RESULT_BACKEND" \
    CELERY_WORKER_CONCURRENCY="$CELERY_WORKER_CONCURRENCY" \
    ./run_worker.sh
}

trap cleanup EXIT INT TERM

echo "ai-engine async stack"
echo "  api   : http://$HOST:$PORT"
echo "  redis : $REDIS_URL"
echo "  worker: concurrency=$CELERY_WORKER_CONCURRENCY"
echo

run_redis
start_service "ai-engine" run_api
start_service "ai-worker" run_worker

echo
echo "ai-engine async stack is starting. Press Ctrl+C to stop it."
wait
