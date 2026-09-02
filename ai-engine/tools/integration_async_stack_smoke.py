#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_DIR.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

sys.path.insert(0, str(ROOT))

from celery.result import AsyncResult
from redis import Redis

from app.config import get_settings
from app.workers.celery_app import celery_app
from app.workers.job_locks import acquire_job_lock, release_job_lock
from app.workers.tasks.image_tasks import generate_image_task
from app.workers.tasks.video_tasks import generate_video_short_task

REQUIRED_QUEUES = {"image-queue", "video-queue"}
TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED"}
ENV_FILE = ROOT / ".env"


@dataclass
class SmokeCheck:
    name: str
    status: str
    detail: str = ""


@dataclass
class EnqueuedTask:
    job_id: str
    result: AsyncResult


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test Redis, Celery workers, queues, and async task results.",
    )
    parser.add_argument("--timeout", type=float, default=45.0, help="Max seconds to wait for each task result")
    parser.add_argument("--poll-interval", type=float, default=0.5, help="Task result polling interval seconds")
    parser.add_argument("--inspect-timeout", type=float, default=3.0, help="Celery inspect timeout seconds")
    parser.add_argument("--skip-jobs", action="store_true", help="Only check Redis and worker queue availability")
    parser.add_argument(
        "--enqueue-provider-jobs",
        action="store_true",
        help="Enqueue image/video provider jobs even outside mock mode. This may call paid providers.",
    )
    parser.add_argument(
        "--allow-live-mode",
        action="store_true",
        help="Deprecated alias for --enqueue-provider-jobs.",
    )
    return parser.parse_args()


def run_smoke(args: argparse.Namespace) -> tuple[int, list[SmokeCheck]]:
    checks: list[SmokeCheck] = []
    settings = get_settings()

    checks.append(check_redis(settings.redis_url))
    if has_failure(checks):
        return 1, checks
    checks.extend(check_redis_runtime_policy(settings.redis_url))

    checks.extend(check_workers(args.inspect_timeout))
    if has_failure(checks) or args.skip_jobs:
        return (1 if has_failure(checks) else 0), checks

    if settings.celery_task_always_eager:
        checks.append(SmokeCheck(
            name="celery_eager_mode",
            status="fail",
            detail="CELERY_TASK_ALWAYS_EAGER must be false for real Redis/Celery integration smoke tests.",
        ))
        return 1, checks

    explicit_provider_jobs = args.enqueue_provider_jobs or args.allow_live_mode
    enqueue_provider_jobs = settings.ai_provider_mode == "mock" or explicit_provider_jobs

    if not enqueue_provider_jobs:
        checks.append(SmokeCheck(
            name="provider_jobs",
            status="skipped",
            detail=(
                "AI_PROVIDER_MODE is not mock, so provider image/video jobs were not enqueued. "
                "Use --enqueue-provider-jobs only when paid provider calls are intended."
            ),
        ))
    else:
        if settings.ai_provider_mode == "mock" and not explicit_provider_jobs:
            dotenv_mode = read_dotenv_value("AI_PROVIDER_MODE")
            if dotenv_mode != "mock":
                checks.append(SmokeCheck(
                    name="provider_jobs",
                    status="fail",
                    detail=(
                        "AI_PROVIDER_MODE=mock is only visible to this smoke process, but .env "
                        f"AI_PROVIDER_MODE is {dotenv_mode or 'unset'}. Set AI_PROVIDER_MODE=mock "
                        "in .env and restart run_async_stack.sh before mock provider job smoke tests. "
                        "Use --enqueue-provider-jobs only when live paid provider calls are intended."
                    ),
                ))
                checks.append(check_duplicate_lock(args.timeout, args.poll_interval))
                return 1, checks

        image_result = enqueue_image_job()
        checks.append(wait_for_result(
            "image_job",
            image_result,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            expected_status="completed",
        ))

        video_result = enqueue_video_short_job()
        checks.append(wait_for_result(
            "video_short_job",
            video_result,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            expected_status="failed" if settings.ai_provider_mode == "mock" else None,
            disallow_keys={"request"},
        ))

    checks.append(check_duplicate_lock(args.timeout, args.poll_interval))

    return (1 if has_failure(checks) else 0), checks


def check_redis(redis_url: str) -> SmokeCheck:
    try:
        client = Redis.from_url(redis_url)
        client.ping()
        client.close()
    except Exception as exc:
        return SmokeCheck("redis", "fail", str(exc))
    return SmokeCheck("redis", "ok", redis_url)


def check_redis_runtime_policy(redis_url: str) -> list[SmokeCheck]:
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        appendonly = _redis_config_value(client, "appendonly")
        maxmemory = _redis_config_value(client, "maxmemory")
        maxmemory_policy = _redis_config_value(client, "maxmemory-policy")
        client.close()
    except Exception as exc:
        return [SmokeCheck("redis_runtime_policy", "warn", f"CONFIG GET unavailable: {exc}")]

    checks = [
        SmokeCheck("redis_appendonly", "ok" if appendonly == "yes" else "warn", f"appendonly={appendonly}"),
        SmokeCheck("redis_maxmemory", "ok" if _positive_int(maxmemory) else "warn", f"maxmemory={maxmemory}"),
        SmokeCheck(
            "redis_maxmemory_policy",
            "ok" if maxmemory_policy == "noeviction" else "warn",
            f"maxmemory-policy={maxmemory_policy}",
        ),
    ]
    return checks


def _redis_config_value(client: Redis, key: str) -> str:
    value = client.config_get(key).get(key)
    return str(value) if value is not None else ""


def _positive_int(value: str) -> bool:
    try:
        return int(value) > 0
    except ValueError:
        return False


def read_dotenv_value(key: str) -> str | None:
    if not ENV_FILE.exists():
        return None
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return None


def check_workers(inspect_timeout: float) -> list[SmokeCheck]:
    inspector = celery_app.control.inspect(timeout=inspect_timeout)
    ping = inspector.ping() or {}
    active_queues = inspector.active_queues() or {}
    checks = [
        SmokeCheck("celery_ping", "ok" if ping else "fail", _json_detail(ping) if ping else "no workers replied"),
    ]
    queues = active_queue_names(active_queues)
    missing = sorted(REQUIRED_QUEUES - queues)
    checks.append(SmokeCheck(
        "active_queues",
        "ok" if not missing else "fail",
        f"queues={sorted(queues)} missing={missing}",
    ))
    return checks


def active_queue_names(active_queues: dict[str, list[dict[str, Any]]]) -> set[str]:
    queues: set[str] = set()
    for worker_queues in active_queues.values():
        for queue in worker_queues or []:
            name = queue.get("name")
            if isinstance(name, str):
                queues.add(name)
    return queues


def enqueue_image_job() -> EnqueuedTask:
    job_id = f"smoke-image-{uuid.uuid4()}"
    result = generate_image_task.apply_async(
        args=[{
            "jobId": job_id,
            "purpose": "promotion",
            "channels": ["instagram"],
            "image_prompt": "Smoke test local cafe promotional image",
            "visual_mood": "bright",
            "n": 1,
        }],
        queue="image-queue",
    )
    return EnqueuedTask(job_id=job_id, result=result)


def enqueue_video_short_job() -> EnqueuedTask:
    job_id = f"smoke-video-{uuid.uuid4()}"
    result = generate_video_short_task.apply_async(
        args=[{
            "jobId": job_id,
            "prompt": "Smoke test short video for a local cafe",
            "model": "fast",
            "platform": "instagram_reels",
            "task": "textToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 4,
        }],
        queue="video-queue",
    )
    return EnqueuedTask(job_id=job_id, result=result)


def enqueue_duplicate_locked_video_job(job_id: str) -> EnqueuedTask:
    result = generate_video_short_task.apply_async(
        args=[{
            "jobId": job_id,
            "prompt": "Duplicate smoke test short video",
            "model": "fast",
            "platform": "instagram_reels",
            "task": "textToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 4,
        }],
        queue="video-queue",
    )
    return EnqueuedTask(job_id=job_id, result=result)


def check_duplicate_lock(timeout: float, poll_interval: float) -> SmokeCheck:
    job_id = f"smoke-duplicate-{uuid.uuid4()}"
    lock = acquire_job_lock(job_id=job_id, job_type="video-short")
    if not lock or lock is True:
        return SmokeCheck("duplicate_lock", "fail", "could not acquire Redis job lock for smoke test")
    try:
        duplicate_result = enqueue_duplicate_locked_video_job(job_id)
        return wait_for_result(
            "duplicate_lock",
            duplicate_result,
            timeout=timeout,
            poll_interval=poll_interval,
            expected_status="duplicate_skipped",
            disallow_keys={"request"},
        )
    finally:
        release_job_lock(lock)


def wait_for_result(
    name: str,
    enqueued: EnqueuedTask,
    *,
    timeout: float,
    poll_interval: float,
    expected_status: str | None = None,
    disallow_keys: set[str] | None = None,
) -> SmokeCheck:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = enqueued.result.state
        if state in TERMINAL_STATES:
            payload = enqueued.result.result
            return validate_result_payload(
                name,
                state=state,
                payload=payload,
                expected_status=expected_status,
                disallow_keys=disallow_keys or set(),
            )
        time.sleep(poll_interval)
    return SmokeCheck(
        name,
        "fail",
        f"timed out waiting for job_id={enqueued.job_id} task_id={enqueued.result.id} state={enqueued.result.state}",
    )


def validate_result_payload(
    name: str,
    *,
    state: str,
    payload: Any,
    expected_status: str | None,
    disallow_keys: set[str],
) -> SmokeCheck:
    if state != "SUCCESS":
        return SmokeCheck(name, "fail", f"task state={state} payload={payload!r}")
    if not isinstance(payload, dict):
        return SmokeCheck(name, "fail", f"result payload is not a dict: {payload!r}")
    status = payload.get("status")
    if expected_status is not None and status != expected_status:
        return SmokeCheck(name, "fail", f"expected status={expected_status}, got {status}: {payload!r}")
    forbidden = sorted(key for key in disallow_keys if key in payload)
    if forbidden:
        return SmokeCheck(name, "fail", f"result payload contains forbidden keys: {forbidden}")
    return SmokeCheck(name, "ok", _json_detail(payload))


def has_failure(checks: list[SmokeCheck]) -> bool:
    return any(check.status == "fail" for check in checks)


def _json_detail(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main() -> int:
    exit_code, checks = run_smoke(parse_args())
    print(json.dumps([asdict(check) for check in checks], ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
