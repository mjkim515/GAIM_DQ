#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CELERY_BIN="${CELERY_BIN:-$SCRIPT_DIR/.venv/bin/celery}"
CELERY_APP="${CELERY_APP:-app.workers.celery_app.celery_app}"
CELERY_QUEUES="${CELERY_QUEUES:-image-queue,video-queue}"
CELERY_WORKER_CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-3}"
CELERY_LOGLEVEL="${CELERY_LOGLEVEL:-info}"

if [[ ! -x "$CELERY_BIN" ]]; then
  echo "celery executable not found: $CELERY_BIN" >&2
  echo "Create the virtualenv and install requirements first." >&2
  exit 1
fi

echo "Starting ai-engine Celery worker"
echo "  app        : $CELERY_APP"
echo "  queues     : $CELERY_QUEUES"
echo "  concurrency: $CELERY_WORKER_CONCURRENCY"

exec "$CELERY_BIN" -A "$CELERY_APP" worker \
  --loglevel="$CELERY_LOGLEVEL" \
  --concurrency="$CELERY_WORKER_CONCURRENCY" \
  -Q "$CELERY_QUEUES"
