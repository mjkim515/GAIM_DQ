import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.core.provider_errors import is_retryable_job_exception, public_job_error_message
from app.schemas.video import VideoRequest, VideoShortCreateRequest
from app.services.callbacks import notify_job_failed
from app.services.video.veo_service import (
    _run_live_video_generation,
    _run_live_video_short_generation,
    resolve_video_short_request,
)
from app.workers.celery_app import celery_app
from app.workers.job_locks import run_with_job_lock

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def generate_video_task(self, request_data: dict) -> dict:
    job_id = _job_id_from_request(request_data)
    try:
        return run_with_job_lock(
            job_id=job_id,
            job_type="video",
            task_id=getattr(self.request, "id", None),
            on_duplicate=lambda: _duplicate_result(job_id),
            run=lambda: _run_video_generation(request_data),
        )
    except Exception as exc:
        if _should_retry(self, exc):
            raise self.retry(exc=exc, countdown=get_settings().celery_task_retry_countdown)
        return _run_async(_notify_video_task_failed, job_id, exc)


@celery_app.task(bind=True, max_retries=2)
def generate_video_short_task(self, request_data: dict) -> dict:
    job_id = _job_id_from_request(request_data)
    try:
        return run_with_job_lock(
            job_id=job_id,
            job_type="video-short",
            task_id=getattr(self.request, "id", None),
            on_duplicate=lambda: _duplicate_result(job_id),
            run=lambda: _run_video_short_generation(request_data),
        )
    except Exception as exc:
        if _should_retry(self, exc):
            raise self.retry(exc=exc, countdown=get_settings().celery_task_retry_countdown)
        return _run_async(_notify_video_task_failed, job_id, exc)


def _run_video_generation(request_data: dict) -> dict:
    request = VideoRequest.model_validate(request_data)
    return _run_async(_run_live_video_generation, request.job_id, request)


def _run_video_short_generation(request_data: dict) -> dict:
    request = VideoShortCreateRequest.model_validate(request_data)
    resolved_request = resolve_video_short_request(request)
    return _run_async(_run_live_video_short_generation, request.job_id, resolved_request)


def _run_async(async_fn, *args):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_fn(*args))
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(async_fn(*args))).result()


def _job_id_from_request(request_data: dict) -> str | None:
    job_id = request_data.get("jobId") or request_data.get("job_id")
    return str(job_id) if job_id else None


async def _notify_video_task_failed(
    job_id: str | None,
    exc: Exception,
) -> dict:
    public_error = public_job_error_message(exc)
    logger.error("Video task failed before completion job_id=%s", job_id, exc_info=exc)
    callback_sent = False
    if job_id:
        callback_sent = await notify_job_failed(job_id, public_error)
    return {
        "jobId": job_id,
        "status": "failed",
        "error": public_error,
        "callbacks": {"failed": callback_sent},
    }


def _should_retry(task, exc: Exception) -> bool:
    settings = get_settings()
    return (
        settings.celery_task_retry_enabled
        and is_retryable_job_exception(exc)
        and task.request.retries < task.max_retries
    )


def _duplicate_result(job_id: str | None) -> dict:
    return {
        "jobId": job_id,
        "status": "duplicate_skipped",
        "callbacks": {},
    }
