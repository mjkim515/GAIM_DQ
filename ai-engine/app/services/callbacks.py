import asyncio
import json
import logging
import random
from urllib import error, request

from app.config import get_settings

logger = logging.getLogger(__name__)
CALLBACK_MAX_ATTEMPTS = 4
CALLBACK_RETRY_BASE_SEC = 0.5
CALLBACK_RETRY_MAX_SEC = 8.0


async def notify_job_progress(job_id: str, progress: int) -> bool:
    return await _post_callback(
        f"/internal/callback/jobs/{job_id}/progress",
        {"progress": progress},
        max_attempts=1,
    )


async def notify_job_completed(
    job_id: str,
    result_url: str,
    duration_ms: int,
    provider: str | None = None,
    model_used: str | None = None,
    fallback_used: bool | None = None,
    warnings: list[str] | None = None,
) -> bool:
    payload: dict[str, object] = {
        "status": "completed",
        "resultUrl": result_url,
        "durationMs": duration_ms,
    }
    if provider is not None:
        payload["provider"] = provider
    if model_used is not None:
        payload["modelUsed"] = model_used
    if fallback_used is not None:
        payload["fallbackUsed"] = fallback_used
    if warnings is not None:
        payload["warnings"] = warnings
    return await _post_callback(f"/internal/callback/jobs/{job_id}", payload)


async def notify_image_job_completed(
    job_id: str,
    images: list[str],
    provider: str,
    model_used: str,
    duration_ms: int,
    fallback_used: bool | None = None,
    warnings: list[str] | None = None,
) -> bool:
    payload: dict[str, object] = {
        "status": "completed",
        "images": images,
        "provider": provider,
        "modelUsed": model_used,
        "durationMs": duration_ms,
    }
    if fallback_used is not None:
        payload["fallbackUsed"] = fallback_used
    if warnings is not None:
        payload["warnings"] = warnings
    return await _post_callback(
        f"/internal/callback/jobs/{job_id}",
        payload,
    )


async def notify_job_failed(job_id: str, error_message: str, duration_ms: int | None = None) -> bool:
    payload: dict[str, object] = {
        "status": "failed",
        "error": error_message,
    }
    if duration_ms is not None:
        payload["durationMs"] = duration_ms
    return await _post_callback(f"/internal/callback/jobs/{job_id}", payload)


async def _post_callback(
    path: str,
    payload: dict[str, object],
    *,
    max_attempts: int | None = None,
) -> bool:
    settings = get_settings()
    base_url = settings.was_base_url.rstrip("/")
    url = f"{base_url}{path}"
    attempts = max_attempts or CALLBACK_MAX_ATTEMPTS

    def send() -> None:
        body = json.dumps(payload).encode("utf-8")
        callback_request = request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": settings.was_internal_token,
            },
        )
        with request.urlopen(callback_request, timeout=settings.was_callback_timeout_sec) as response:
            response.read()

    for attempt in range(1, attempts + 1):
        try:
            await asyncio.to_thread(send)
            return True
        except (OSError, TimeoutError, error.URLError, error.HTTPError) as exc:
            if attempt >= attempts:
                logger.warning("WAS callback failed for %s after %s attempts: %s", url, attempt, exc)
                return False
            logger.info("WAS callback retrying for %s attempt=%s error=%s", url, attempt, exc)
            await asyncio.sleep(_callback_retry_delay(attempt))
    return False


def _callback_retry_delay(attempt: int) -> float:
    delay = min(CALLBACK_RETRY_BASE_SEC * 2 ** (attempt - 1), CALLBACK_RETRY_MAX_SEC)
    return delay + random.uniform(0, 0.5)
