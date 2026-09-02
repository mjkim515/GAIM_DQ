#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

load_dotenv_if_present() {
  local line
  local key
  local value

  if [[ ! -f "$ENV_FILE" ]]; then
    return
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ -z "$line" || "$line" == \#* || "$line" != *=* ]]; then
      continue
    fi

    key="${line%%=*}"
    value="${line#*=}"
    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      continue
    fi
    if [[ -n "${!key:-}" ]]; then
      continue
    fi

    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    export "$key=$value"
  done < "$ENV_FILE"
}

load_dotenv_if_present

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8002}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_URL="${REDIS_URL:-redis://$REDIS_HOST:$REDIS_PORT/0}"
CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://$REDIS_HOST:$REDIS_PORT/1}"
CELERY_WORKER_CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-3}"
CELERY_IMAGE_QUEUES="${CELERY_IMAGE_QUEUES:-image-queue}"
CELERY_VIDEO_QUEUES="${CELERY_VIDEO_QUEUES:-video-queue}"
CELERY_IMAGE_WORKER_CONCURRENCY="${CELERY_IMAGE_WORKER_CONCURRENCY:-$CELERY_WORKER_CONCURRENCY}"
CELERY_VIDEO_WORKER_CONCURRENCY="${CELERY_VIDEO_WORKER_CONCURRENCY:-1}"
CELERY_IMAGE_WORKER_NAME="${CELERY_IMAGE_WORKER_NAME:-ai-image-worker@%h}"
CELERY_VIDEO_WORKER_NAME="${CELERY_VIDEO_WORKER_NAME:-ai-video-worker@%h}"
CELERY_WORKER_PATTERN="${CELERY_WORKER_PATTERN:-celery.*app.workers.celery_app.celery_app}"

PIDS=()

wait_for_redis() {
  local attempts="${REDIS_READY_ATTEMPTS:-30}"
  local delay="${REDIS_READY_DELAY_SEC:-1}"
  local python_bin="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
  local attempt

  if [[ ! -x "$python_bin" ]]; then
    echo "Python executable not found for Redis readiness check: $python_bin" >&2
    return 1
  fi

  echo "Waiting for Redis readiness..."
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if REDIS_URL="$REDIS_URL" "$python_bin" -c 'import os
from redis import Redis
client = Redis.from_url(os.environ["REDIS_URL"])
client.ping()
client.close()
' >/dev/null 2>&1; then
      echo "Redis is ready: $REDIS_URL"
      return 0
    fi
    sleep "$delay"
  done

  echo "Redis did not become ready after $attempts attempts: $REDIS_URL" >&2
  return 1
}

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

stop_celery_workers() {
  local pids

  print_celery_processes "Celery worker processes before cleanup:"

  pids="$(pgrep -f "$CELERY_WORKER_PATTERN" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return
  fi

  echo "Stopping ai-engine Celery worker process(es): $pids"
  kill $pids 2>/dev/null || true

  local waited=0
  while [[ "$waited" -lt 5 ]]; do
    pids="$(pgrep -f "$CELERY_WORKER_PATTERN" 2>/dev/null || true)"
    if [[ -z "$pids" ]]; then
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done

  pids="$(pgrep -f "$CELERY_WORKER_PATTERN" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Force stopping ai-engine Celery worker process(es): $pids"
    kill -9 $pids 2>/dev/null || true
  fi

  print_celery_processes "Celery worker processes after cleanup:"
}

cleanup() {
  local pid

  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo
    echo "Stopping ai-engine async stack..."
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
      fi
    done
  fi

  stop_celery_workers
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
  REDIS_HOST="$REDIS_HOST" \
    REDIS_PORT="$REDIS_PORT" \
    REDIS_CONTAINER_NAME="${REDIS_CONTAINER_NAME:-gaim-ai-engine-redis}" \
    REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}" \
    REDIS_DATA_VOLUME="${REDIS_DATA_VOLUME:-gaim-ai-engine-redis-data}" \
    REDIS_DATA_DIR="${REDIS_DATA_DIR:-}" \
    REDIS_APPENDONLY="${REDIS_APPENDONLY:-yes}" \
    REDIS_MAXMEMORY="${REDIS_MAXMEMORY:-512mb}" \
    REDIS_MAXMEMORY_POLICY="${REDIS_MAXMEMORY_POLICY:-noeviction}" \
    REDIS_REQUIREPASS="${REDIS_REQUIREPASS:-}" \
    ./run_redis.sh
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

run_image_worker() {
  cd "$SCRIPT_DIR"
  REDIS_URL="$REDIS_URL" \
    CELERY_BROKER_URL="$CELERY_BROKER_URL" \
    CELERY_RESULT_BACKEND="$CELERY_RESULT_BACKEND" \
    CELERY_QUEUES="$CELERY_IMAGE_QUEUES" \
    CELERY_WORKER_CONCURRENCY="$CELERY_IMAGE_WORKER_CONCURRENCY" \
    CELERY_WORKER_NAME="$CELERY_IMAGE_WORKER_NAME" \
    ./run_worker.sh
}

run_video_worker() {
  cd "$SCRIPT_DIR"
  REDIS_URL="$REDIS_URL" \
    CELERY_BROKER_URL="$CELERY_BROKER_URL" \
    CELERY_RESULT_BACKEND="$CELERY_RESULT_BACKEND" \
    CELERY_QUEUES="$CELERY_VIDEO_QUEUES" \
    CELERY_WORKER_CONCURRENCY="$CELERY_VIDEO_WORKER_CONCURRENCY" \
    CELERY_WORKER_NAME="$CELERY_VIDEO_WORKER_NAME" \
    ./run_worker.sh
}

trap cleanup EXIT INT TERM

echo "ai-engine async stack"
echo "  api   : http://$HOST:$PORT"
echo "  redis : $REDIS_URL"
echo "  image worker: queues=$CELERY_IMAGE_QUEUES concurrency=$CELERY_IMAGE_WORKER_CONCURRENCY name=$CELERY_IMAGE_WORKER_NAME"
echo "  video worker: queues=$CELERY_VIDEO_QUEUES concurrency=$CELERY_VIDEO_WORKER_CONCURRENCY name=$CELERY_VIDEO_WORKER_NAME"
echo

stop_celery_workers
run_redis
wait_for_redis
start_service "ai-engine" run_api
start_service "ai-image-worker" run_image_worker
start_service "ai-video-worker" run_video_worker

echo
echo "ai-engine async stack is starting. Press Ctrl+C to stop it."
wait
