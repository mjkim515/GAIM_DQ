import logging
from typing import Any

from celery.result import AsyncResult
from redis import Redis

from app.config import get_settings
from app.schemas.common import JobStatus

logger = logging.getLogger(__name__)

_MEMORY_TASK_IDS: dict[tuple[str, str], str] = {}


def remember_job_task(job_type: str, job_id: str, task_id: str | None) -> None:
    if not task_id:
        return
    _MEMORY_TASK_IDS[(job_type, job_id)] = task_id
    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url)
        client.set(_task_key(job_type, job_id), task_id, ex=settings.job_status_ttl_seconds)
        client.close()
    except Exception as exc:
        logger.warning("Could not persist %s job task mapping job_id=%s: %s", job_type, job_id, exc)


def get_remembered_task_id(job_type: str, job_id: str) -> str | None:
    task_id = _MEMORY_TASK_IDS.get((job_type, job_id))
    if task_id:
        return task_id
    try:
        client = Redis.from_url(get_settings().redis_url, decode_responses=True)
        task_id = client.get(_task_key(job_type, job_id))
        client.close()
    except Exception as exc:
        logger.warning("Could not read %s job task mapping job_id=%s: %s", job_type, job_id, exc)
        return None
    if isinstance(task_id, str) and task_id:
        _MEMORY_TASK_IDS[(job_type, job_id)] = task_id
        return task_id
    return None


def celery_result_payload_for_job(job_type: str, job_id: str) -> dict[str, Any] | None:
    task_id = get_remembered_task_id(job_type, job_id)
    if not task_id:
        return None
    from app.workers.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    state = result.state
    if state == "PENDING":
        return {"jobId": job_id, "status": JobStatus.queued.value, "progressPct": 0}
    if state in {"STARTED", "RETRY"}:
        return {"jobId": job_id, "status": JobStatus.processing.value, "progressPct": 5}
    if state == "SUCCESS":
        payload = result.result
        if isinstance(payload, dict):
            return {"jobId": job_id, **payload}
        return {"jobId": job_id, "status": JobStatus.failed.value, "error": "Job result payload was not readable."}
    if state in {"FAILURE", "REVOKED"}:
        return {"jobId": job_id, "status": JobStatus.failed.value, "error": str(result.result)}
    return {"jobId": job_id, "status": JobStatus.processing.value}


def _task_key(job_type: str, job_id: str) -> str:
    return f"gaim:ai-engine:job-status:{job_type}:{job_id}"
