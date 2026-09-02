#!/usr/bin/env bash
set -euo pipefail

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_CONTAINER_NAME="${REDIS_CONTAINER_NAME:-gaim-ai-engine-redis}"
REDIS_IMAGE="${REDIS_IMAGE:-redis:7-alpine}"
REDIS_DATA_VOLUME="${REDIS_DATA_VOLUME:-gaim-ai-engine-redis-data}"
REDIS_DATA_DIR="${REDIS_DATA_DIR:-}"
REDIS_APPENDONLY="${REDIS_APPENDONLY:-yes}"
REDIS_MAXMEMORY="${REDIS_MAXMEMORY:-512mb}"
REDIS_MAXMEMORY_POLICY="${REDIS_MAXMEMORY_POLICY:-noeviction}"
REDIS_REQUIREPASS="${REDIS_REQUIREPASS:-}"
DOCKER_BIN="${DOCKER_BIN:-docker}"

if lsof -tiTCP:"$REDIS_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Redis port already in use at $REDIS_HOST:$REDIS_PORT. Reusing existing Redis."
  exit 0
fi

if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
  echo "Docker is required to start Redis automatically." >&2
  echo "Install/start Docker, or run Redis manually on $REDIS_HOST:$REDIS_PORT." >&2
  exit 1
fi

if "$DOCKER_BIN" ps --format '{{.Names}}' | grep -qx "$REDIS_CONTAINER_NAME"; then
  echo "Redis container already running: $REDIS_CONTAINER_NAME"
  exit 0
fi

if "$DOCKER_BIN" ps -a --format '{{.Names}}' | grep -qx "$REDIS_CONTAINER_NAME"; then
  echo "Starting existing Redis container: $REDIS_CONTAINER_NAME"
  "$DOCKER_BIN" start "$REDIS_CONTAINER_NAME" >/dev/null
else
  echo "Creating Redis container: $REDIS_CONTAINER_NAME"
  REDIS_ARGS=(
    redis-server
    --appendonly "$REDIS_APPENDONLY"
    --maxmemory "$REDIS_MAXMEMORY"
    --maxmemory-policy "$REDIS_MAXMEMORY_POLICY"
  )
  VOLUME_ARGS=()
  if [[ -n "$REDIS_DATA_DIR" ]]; then
    mkdir -p "$REDIS_DATA_DIR"
    VOLUME_ARGS=(-v "$REDIS_DATA_DIR:/data")
  else
    VOLUME_ARGS=(-v "$REDIS_DATA_VOLUME:/data")
  fi
  if [[ -n "$REDIS_REQUIREPASS" ]]; then
    REDIS_ARGS+=(--requirepass "$REDIS_REQUIREPASS")
  fi
  "$DOCKER_BIN" run -d \
    --name "$REDIS_CONTAINER_NAME" \
    -p "$REDIS_PORT:6379" \
    "${VOLUME_ARGS[@]}" \
    "$REDIS_IMAGE" \
    "${REDIS_ARGS[@]}" >/dev/null
fi

if [[ -n "$REDIS_REQUIREPASS" ]]; then
  echo "Redis is available at redis://:<password>@$REDIS_HOST:$REDIS_PORT/0"
else
  echo "Redis is available at redis://$REDIS_HOST:$REDIS_PORT/0"
fi
