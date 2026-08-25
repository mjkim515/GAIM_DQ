import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.schemas.video import VideoRequest, VideoShortCreateRequest
from app.services.video.veo_service import (
    _run_live_video_generation,
    _run_live_video_short_generation,
    resolve_video_short_request,
)
from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=2)
def generate_video_task(self, request_data: dict) -> dict:
    request = VideoRequest.model_validate(request_data)
    _run_async(_run_live_video_generation, request.job_id, request)
    return {
        "jobId": request.job_id,
        "status": "queued",
        "request": request_data,
    }


@celery_app.task(bind=True, max_retries=2)
def generate_video_short_task(self, request_data: dict) -> dict:
    request = VideoShortCreateRequest.model_validate(request_data)
    resolved_request = resolve_video_short_request(request)
    _run_async(_run_live_video_short_generation, request.job_id, resolved_request)
    return {
        "jobId": request.job_id,
        "status": "queued",
        "request": request_data,
    }


def _run_async(async_fn, *args):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_fn(*args))
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(async_fn(*args))).result()
