import json
import time
from urllib import error, request

from app.config import get_settings
from app.core.exceptions import ProviderAuthenticationError, ProviderRequestError
from app.core.media_limits import decode_limited_base64
from app.core.provider_errors import classify_runway_exception
from app.schemas.video import ResolvedVideoShortRequest, VideoShortMediaInput

RUNWAY_SUCCEEDED_STATUSES = {"SUCCEEDED"}
RUNWAY_FAILED_STATUSES = {"FAILED", "CANCELED", "CANCELLED"}
RUNWAY_MIN_DURATION_SECONDS = 2
RUNWAY_MAX_DURATION_SECONDS = 10


def generate_runway_video_short_sync(request_data: ResolvedVideoShortRequest, model: str) -> bytes:
    settings = get_settings()
    if not settings.runwayml_api_secret:
        raise ProviderAuthenticationError("Runway provider authentication failed.")
    if model not in settings.runway_video_models:
        raise ProviderRequestError(f"Unsupported Runway video model: {model}")

    payload = _build_runway_payload(request_data, model)
    endpoint = "image_to_video" if "promptImage" in payload else "text_to_video"
    task = _runway_json_request("POST", f"{settings.runway_api_base_url}/{endpoint}", payload, settings)
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise ProviderRequestError("Runway task response did not include an id.")

    deadline = time.monotonic() + settings.video_max_wait_sec
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("Runway video generation timed out")
        task_detail = _runway_json_request("GET", f"{settings.runway_api_base_url}/tasks/{task_id}", None, settings)
        status = str(task_detail.get("status") or "").upper()
        if status in RUNWAY_SUCCEEDED_STATUSES:
            output = task_detail.get("output")
            if not isinstance(output, list) or not output or not isinstance(output[0], str):
                raise ProviderRequestError("Runway task succeeded without a video output URL.")
            return _download_runway_output(output[0])
        if status in RUNWAY_FAILED_STATUSES:
            raise ProviderRequestError("Runway video generation failed.")
        time.sleep(max(5, settings.video_poll_interval_sec))


def _build_runway_payload(request_data: ResolvedVideoShortRequest, model: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "promptText": _to_runway_prompt_text(request_data.final_prompt),
        "ratio": _to_runway_ratio(request_data.aspect_ratio),
        "duration": _to_runway_duration(request_data.duration_seconds),
    }
    if request_data.seed is not None:
        payload["seed"] = request_data.seed
    prompt_image = _first_runway_prompt_image(request_data)
    if prompt_image:
        payload["promptImage"] = prompt_image
    return payload


def _to_runway_ratio(aspect_ratio: str) -> str:
    return {
        "16:9": "1280:720",
        "9:16": "720:1280",
    }[aspect_ratio]


def _to_runway_prompt_text(prompt: str) -> str:
    return prompt[:1000]


def _to_runway_duration(duration_seconds: int) -> int:
    if not RUNWAY_MIN_DURATION_SECONDS <= duration_seconds <= RUNWAY_MAX_DURATION_SECONDS:
        raise ProviderRequestError("Runway video duration must be between 2 and 10 seconds.")
    return duration_seconds


def _first_runway_prompt_image(request_data: ResolvedVideoShortRequest) -> str | None:
    if not request_data.input:
        return None
    if request_data.input.image:
        return _to_runway_prompt_image(request_data.input.image)
    if request_data.input.reference_images:
        return _to_runway_prompt_image(request_data.input.reference_images[0])
    return None


def _to_runway_prompt_image(media: VideoShortMediaInput) -> str:
    if media.gcs_uri:
        if media.gcs_uri.startswith(("http://", "https://")):
            return media.gcs_uri
        raise ProviderRequestError("Runway fallback requires an HTTP image URL or uploaded image bytes.")
    if not media.bytes_base64_encoded:
        raise ProviderRequestError("Runway fallback image input is missing bytesBase64Encoded.")
    try:
        decode_limited_base64(
            media.bytes_base64_encoded,
            max_bytes=get_settings().max_video_input_image_bytes,
            label="Runway fallback image input",
        )
    except ValueError as exc:
        raise ProviderRequestError("Runway fallback image input is not valid base64.") from exc
    return f"data:{media.mime_type};base64,{media.bytes_base64_encoded}"


def _runway_json_request(method: str, url: str, payload: dict[str, object] | None, settings) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.runwayml_api_secret}",
            "Content-Type": "application/json",
            "X-Runway-Version": settings.runway_api_version,
        },
    )
    try:
        with request.urlopen(req, timeout=settings.runway_request_timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise classify_runway_exception(exc) from exc


def _download_runway_output(url: str) -> bytes:
    settings = get_settings()
    try:
        with request.urlopen(url, timeout=settings.runway_download_timeout_sec) as response:
            return response.read()
    except error.URLError as exc:
        raise classify_runway_exception(exc) from exc
