import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.provider_errors import public_job_error_message
from app.schemas.image import ImageJobRequest, ImageRequest
from app.services.callbacks import notify_image_job_completed, notify_job_failed, notify_job_progress
from app.services.image.create_service import create_image
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def generate_image_task(self, request_data: dict) -> dict:
    return _run_async(_run_image_job, request_data)


async def _run_image_job(request_data: dict) -> dict:
    started_at = time.monotonic()
    job_request = ImageJobRequest.model_validate(request_data)
    job_id = job_request.job_id

    try:
        await notify_job_progress(job_id, 5)
        image_request = ImageRequest.model_validate(job_request.model_dump(exclude={"job_id"}))
        result = await create_image(image_request)
        await notify_job_progress(job_id, 90)
        duration_ms = _elapsed_ms(started_at)
        await notify_image_job_completed(
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
        }
    except Exception as exc:
        duration_ms = _elapsed_ms(started_at)
        public_error = public_job_error_message(exc)
        logger.exception("Image job failed job_id=%s", job_id)
        await notify_job_failed(job_id, public_error, duration_ms)
        return {
            "jobId": job_id,
            "status": "failed",
            "error": public_error,
            "durationMs": duration_ms,
        }


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _run_async(async_fn, *args):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_fn(*args))
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(async_fn(*args))).result()
