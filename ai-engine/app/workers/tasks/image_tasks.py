import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.core.provider_errors import is_retryable_job_exception, public_job_error_message
from app.schemas.image import ImageJobRequest, ImageRequest
from app.services.callbacks import notify_image_job_completed, notify_job_failed, notify_job_progress
from app.services.image.create_service import create_image
from app.workers.celery_app import celery_app
from app.workers.job_locks import run_with_job_lock

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def generate_image_task(self, request_data: dict) -> dict:
    job_id = _job_id_from_request(request_data)
    try:
        return run_with_job_lock(
            job_id=job_id,
            job_type="image",
            on_duplicate=lambda: _duplicate_result(job_id),
            run=lambda: _run_async(_run_image_job, request_data),
        )
    except Exception as exc:
        if _should_retry(self, exc):
            raise self.retry(exc=exc, countdown=get_settings().celery_task_retry_countdown)
        return _run_async(_notify_image_task_failed, job_id, exc)


async def _run_image_job(request_data: dict) -> dict:
    started_at = time.monotonic()
    job_request = ImageJobRequest.model_validate(request_data)
    job_id = job_request.job_id

    try:
        callback_results: dict[str, bool] = {}
        callback_results["started"] = await notify_job_progress(job_id, 5)
        image_request = ImageRequest.model_validate(job_request.model_dump(exclude={"job_id"}))
        result = await create_image(image_request)
        callback_results["finalizing"] = await notify_job_progress(job_id, 90)
        duration_ms = _elapsed_ms(started_at)
        callback_results["completed"] = await notify_image_job_completed(
            job_id=job_id,
            images=result.images,
            provider=result.provider,
            model_used=result.model_used,
            duration_ms=duration_ms,
        )
        return {
            "jobId": job_id,
            "status": "completed",
            "images": result.images,
            "provider": result.provider,
            "modelUsed": result.model_used,
            "durationMs": duration_ms,
            "callbacks": callback_results,
        }
    except Exception as exc:
        if get_settings().celery_task_retry_enabled and is_retryable_job_exception(exc):
            raise
        return await _notify_image_task_failed(job_id, exc, started_at)


async def _notify_image_task_failed(
    job_id: str | None,
    exc: Exception,
    started_at: float | None = None,
) -> dict:
    duration_ms = _elapsed_ms(started_at) if started_at is not None else None
    public_error = public_job_error_message(exc)
    logger.error("Image job failed job_id=%s", job_id, exc_info=exc)
    callback_sent = False
    if job_id:
        callback_sent = await notify_job_failed(job_id, public_error, duration_ms)
    return {
        "jobId": job_id,
        "status": "failed",
        "error": public_error,
        "durationMs": duration_ms,
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


def _job_id_from_request(request_data: dict) -> str | None:
    job_id = request_data.get("jobId") or request_data.get("job_id")
    return str(job_id) if job_id else None


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _run_async(async_fn, *args):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_fn(*args))
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(async_fn(*args))).result()
