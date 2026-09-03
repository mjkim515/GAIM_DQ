import asyncio
import logging
import re
import time

from app.config import get_settings
from app.core.exceptions import AIEngineError, ProviderTimeoutError, RequestValidationError
from app.core.media_limits import decode_limited_base64
from app.core.provider_errors import (
    classify_google_exception,
    is_retryable_job_exception,
    provider_warning_message,
    public_job_error_message,
)
from app.schemas.common import JobStatus
from app.schemas.video import (
    ResolvedVideoShortRequest,
    VideoJobResponse,
    VideoRequest,
    VideoShortCreateRequest,
    VideoShortMediaInput,
    VideoStatusResponse,
)
from app.services.callbacks import notify_job_completed, notify_job_failed, notify_job_progress
from app.services.image.google_service import build_google_video_client
from app.services.text.prompts import append_visual_safety_guardrails
from app.services.video.model_router import (
    build_video_short_candidates,
    deserialize_video_candidates,
    serialize_video_candidates,
)
from app.services.video.runway_service import generate_runway_video_short_sync
from app.services.video.storage import store_video
from app.services.job_status import celery_result_payload_for_job, remember_job_task, record_terminal_status

VIDEO_JOB_TTL_SECONDS = 12 * 60 * 60
_JOBS: dict[str, VideoStatusResponse] = {}
_JOB_UPDATED_AT: dict[str, float] = {}
DEPRECATED_VEO_MODELS = {
    "veo-2.0-generate-001",
    "veo-3.0-generate-001",
    "veo-3.0-fast-generate-001",
}
VIDEO_SHORT_PLATFORM_LABELS = {
    "youtube_shorts": "YouTube Shorts",
    "instagram_reels": "Instagram Reels",
    "tiktok": "TikTok",
    "naver_clip": "Naver Clip",
}

logger = logging.getLogger(__name__)


def _cleanup_expired_jobs(now: float | None = None) -> None:
    now = now or time.time()
    expired_job_ids = [
        job_id for job_id, updated_at in _JOB_UPDATED_AT.items()
        if now - updated_at >= VIDEO_JOB_TTL_SECONDS
    ]
    orphan_job_ids = [
        job_id for job_id in _JOBS
        if job_id not in _JOB_UPDATED_AT
    ]
    for job_id in expired_job_ids + orphan_job_ids:
        _JOBS.pop(job_id, None)
        _JOB_UPDATED_AT.pop(job_id, None)


def _set_job_status(job_id: str, status: VideoStatusResponse) -> None:
    _cleanup_expired_jobs()
    _JOBS[job_id] = status
    _JOB_UPDATED_AT[job_id] = time.time()


def _get_job_status(job_id: str) -> VideoStatusResponse | None:
    _cleanup_expired_jobs()
    return _JOBS.get(job_id)


def _is_mp4_bytes(data: bytes) -> bool:
    return len(data) > 12 and data[4:8] == b"ftyp"


async def _store_generated_video(data: bytes) -> str:
    if not _is_mp4_bytes(data):
        raise RuntimeError("Generated video bytes are not a playable MP4")
    return await store_video(data)


def _set_mock_video_status(job_id: str) -> None:
    message = "Mock video generation does not create playable MP4. Set AI_PROVIDER_MODE=live to generate video."
    _set_job_status(job_id, VideoStatusResponse(
        job_id=job_id,
        status=JobStatus.failed,
        error=message,
        progress_pct=100,
    ))
    asyncio.create_task(notify_job_failed(job_id, message))


async def _set_mock_video_status_async(job_id: str, started_at: float | None = None) -> dict[str, object]:
    message = "Mock video generation does not create playable MP4. Set AI_PROVIDER_MODE=live to generate video."
    status = VideoStatusResponse(
        job_id=job_id,
        status=JobStatus.failed,
        error=message,
        progress_pct=100,
    )
    _set_job_status(job_id, status)
    duration_ms = _elapsed_ms(started_at) if started_at is not None else None
    callback_sent = await notify_job_failed(job_id, message, duration_ms)
    return _video_task_result(status, duration_ms, {"failed": callback_sent})


async def enqueue_video_generation(request: VideoRequest) -> VideoJobResponse:
    provider_model = resolve_video_provider_model(request.model)
    validate_google_video_model(provider_model)
    request = request.model_copy(update={"model": provider_model})
    job_id = request.job_id
    existing_job = _get_job_status(job_id)
    if existing_job is not None:
        return VideoJobResponse(
            job_id=job_id,
            status=existing_job.status,
            message="이미 등록된 jobId입니다. 기존 영상 생성 작업을 반환합니다.",
        )
    _set_job_status(job_id, VideoStatusResponse(
        job_id=job_id,
        status=JobStatus.queued,
        progress_pct=0,
    ))
    from app.workers.tasks.video_tasks import generate_video_task

    result = generate_video_task.apply_async(args=[request.model_dump(by_alias=True)], queue="video-queue")
    remember_job_task("video", job_id, getattr(result, "id", None))
    return VideoJobResponse(
        job_id=job_id,
        status=JobStatus.queued,
        message=f"영상 생성이 시작되었습니다. duration_seconds={request.duration_seconds}",
    )


async def enqueue_video_short_generation(request: VideoShortCreateRequest) -> VideoJobResponse:
    resolved_request = resolve_video_short_request(request)
    job_id = request.job_id
    existing_job = _get_job_status(job_id)
    if existing_job is not None:
        return VideoJobResponse(
            job_id=job_id,
            status=existing_job.status,
            message="이미 등록된 jobId입니다. 기존 영상 생성 작업을 반환합니다.",
        )
    _set_job_status(job_id, VideoStatusResponse(
        job_id=job_id,
        status=JobStatus.queued,
        progress_pct=0,
    ))
    from app.workers.tasks.video_tasks import generate_video_short_task

    result = generate_video_short_task.apply_async(args=[request.model_dump(by_alias=True)], queue="video-queue")
    remember_job_task("video", job_id, getattr(result, "id", None))
    return VideoJobResponse(
        job_id=job_id,
        status=JobStatus.queued,
        message=f"숏폼 영상 생성이 시작되었습니다. task={resolved_request.task}",
    )


async def get_video_status(job_id: str) -> VideoStatusResponse:
    memory_status = _get_job_status(job_id)
    if memory_status is not None:
        return memory_status
    payload = celery_result_payload_for_job("video", job_id)
    if payload is not None:
        return VideoStatusResponse.model_validate(payload)
    return VideoStatusResponse(
        job_id=job_id,
        status=JobStatus.failed,
        error="Unknown job_id",
        progress_pct=100,
    )


async def _run_live_video_short_generation(job_id: str, request: ResolvedVideoShortRequest) -> dict[str, object]:
    started_at = time.monotonic()
    if not get_settings().is_live_ai_enabled:
        return await _set_mock_video_status_async(job_id, started_at)
    try:
        callback_results: dict[str, bool] = {}
        _set_job_status(job_id, VideoStatusResponse(job_id=job_id, status=JobStatus.processing, progress_pct=5))
        callback_results["started"] = await notify_job_progress(job_id, 5)
        video_bytes, provider, model_used, fallback_used, warnings = await asyncio.to_thread(
            _generate_video_short_with_fallback_sync,
            request,
        )
        _set_job_status(job_id, VideoStatusResponse(job_id=job_id, status=JobStatus.processing, progress_pct=90))
        callback_results["finalizing"] = await notify_job_progress(job_id, 90)
        video_url = await _store_generated_video(video_bytes)
        status = VideoStatusResponse(
            job_id=job_id,
            status=JobStatus.completed,
            video_url=video_url,
            progress_pct=100,
            provider=provider,
            model_used=model_used,
            fallback_used=fallback_used,
            warnings=warnings,
        )
        _set_job_status(job_id, status)
        duration_ms = _elapsed_ms(started_at)
        callback_results["completed"] = await notify_job_completed(
            job_id,
            video_url,
            duration_ms,
            provider=provider,
            model_used=model_used,
            fallback_used=fallback_used,
            warnings=warnings,
        )
        return _video_task_result(status, duration_ms, callback_results)
    except Exception as exc:
        normalized_exc = _normalize_video_provider_exception(exc)
        if is_retryable_job_exception(normalized_exc):
            raise normalized_exc
        public_error = public_job_error_message(normalized_exc)
        logger.exception("Video short job failed job_id=%s model=%s", job_id, request.provider_model)
        status = VideoStatusResponse(
            job_id=job_id,
            status=JobStatus.failed,
            error=public_error,
            progress_pct=100,
        )
        _set_job_status(job_id, status)
        duration_ms = _elapsed_ms(started_at)
        callback_sent = await notify_job_failed(job_id, public_error, duration_ms)
        return _video_task_result(status, duration_ms, {"failed": callback_sent})


async def _run_live_video_generation(job_id: str, request: VideoRequest) -> dict[str, object]:
    started_at = time.monotonic()
    if not get_settings().is_live_ai_enabled:
        return await _set_mock_video_status_async(job_id, started_at)
    try:
        callback_results: dict[str, bool] = {}
        _set_job_status(job_id, VideoStatusResponse(job_id=job_id, status=JobStatus.processing, progress_pct=5))
        callback_results["started"] = await notify_job_progress(job_id, 5)
        video_bytes = await asyncio.to_thread(_generate_veo_video_sync, request)
        _set_job_status(job_id, VideoStatusResponse(job_id=job_id, status=JobStatus.processing, progress_pct=90))
        callback_results["finalizing"] = await notify_job_progress(job_id, 90)
        video_url = await _store_generated_video(video_bytes)
        status = VideoStatusResponse(
            job_id=job_id,
            status=JobStatus.completed,
            video_url=video_url,
            progress_pct=100,
        )
        _set_job_status(job_id, status)
        duration_ms = _elapsed_ms(started_at)
        callback_results["completed"] = await notify_job_completed(job_id, video_url, duration_ms)
        return _video_task_result(status, duration_ms, callback_results)
    except Exception as exc:
        normalized_exc = _normalize_video_provider_exception(exc)
        if is_retryable_job_exception(normalized_exc):
            raise normalized_exc
        public_error = public_job_error_message(normalized_exc)
        logger.exception("Video job failed job_id=%s model=%s", job_id, request.model)
        status = VideoStatusResponse(
            job_id=job_id,
            status=JobStatus.failed,
            error=public_error,
            progress_pct=100,
        )
        _set_job_status(job_id, status)
        duration_ms = _elapsed_ms(started_at)
        callback_sent = await notify_job_failed(job_id, public_error, duration_ms)
        return _video_task_result(status, duration_ms, {"failed": callback_sent})


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _video_task_result(
    status: VideoStatusResponse,
    duration_ms: int | None,
    callbacks: dict[str, bool],
) -> dict[str, object]:
    result = status.model_dump(by_alias=True, mode="json")
    result["durationMs"] = duration_ms
    result["callbacks"] = callbacks
    if status.status in {JobStatus.completed, JobStatus.failed}:
        record_terminal_status("video", status.job_id, result)
    return result


def _normalize_video_provider_exception(exc: Exception) -> Exception:
    if isinstance(exc, AIEngineError):
        return exc
    return classify_google_exception(exc)


def resolve_video_short_request(request: VideoShortCreateRequest) -> ResolvedVideoShortRequest:
    advanced = request.advanced
    settings = get_settings()
    effective_duration_seconds = 8 if request.inferred_task == "referenceToVideo" else request.duration_seconds
    candidates = build_video_short_candidates(request.model, request.inferred_task, settings, request.provider_override)
    primary = candidates[0]
    if primary.provider == "google":
        validate_google_video_model(primary.model, settings)
    final_prompt = _build_video_short_prompt_fields(
        prompt=request.prompt,
        platform=request.platform,
        aspect_ratio=request.aspect_ratio,
        duration_seconds=effective_duration_seconds,
        task=request.inferred_task,
        has_start_frame=bool(request.input and request.input.image),
        has_last_frame=bool(request.input and request.input.last_frame),
        has_reference_images=bool(request.input and request.input.reference_images),
        metadata=request.metadata,
    )
    return ResolvedVideoShortRequest(
        provider_model=primary.model,
        provider=primary.provider,
        provider_candidates=serialize_video_candidates(candidates),
        prompt=request.prompt,
        final_prompt=final_prompt,
        task=request.inferred_task,
        platform=request.platform,
        aspect_ratio=request.aspect_ratio,
        duration_seconds=effective_duration_seconds,
        input=request.input,
        sample_count=advanced.sample_count if advanced and advanced.sample_count is not None else 1,
        resolution=advanced.resolution if advanced and advanced.resolution is not None else "720p",
        enhance_prompt=advanced.enhance_prompt if advanced and advanced.enhance_prompt is not None else True,
        generate_audio=advanced.generate_audio if advanced and advanced.generate_audio is not None else True,
        compression_quality=(
            advanced.compression_quality if advanced and advanced.compression_quality is not None else "optimized"
        ),
        resize_mode=advanced.resize_mode if advanced and advanced.resize_mode is not None else "crop",
        negative_prompt=advanced.negative_prompt if advanced else None,
        person_generation=advanced.person_generation if advanced else None,
        seed=advanced.seed if advanced else None,
        storage_uri=advanced.storage_uri if advanced else None,
        pubsub_topic=advanced.pubsub_topic if advanced else None,
        metadata=request.metadata,
    )


def resolve_video_provider_model(model: str, settings=None) -> str:
    settings = settings or get_settings()
    return {
        "standard": settings.google_standard_video_model,
        "fast": settings.google_fast_video_model,
        "lite": settings.google_lite_video_model,
    }.get(model, model)


def validate_google_video_model(model: str, settings=None) -> None:
    settings = settings or get_settings()
    if model in DEPRECATED_VEO_MODELS:
        raise RequestValidationError(
            f"Unsupported Google video model: {model}. Veo 3.0 was shut down on 2026-06-30."
        )
    if model not in settings.google_video_models:
        raise RequestValidationError(f"Unsupported Google video model: {model}")


def _strip_conflicting_video_prompt_options(prompt: str) -> str:
    cleaned = prompt.strip()
    option_patterns = [
        r"(?:YouTube\s+Shorts?|유튜브\s*쇼츠?|쇼츠|Shorts|Instagram\s+Reels?|인스타그램\s*릴스?|릴스|TikTok|틱톡|Naver\s+Clip|네이버\s*클립)\s*용?",
        r"\b(?:9\s*:\s*16|16\s*:\s*9)\b\s*(?:세로형|가로형|vertical|horizontal)?",
        r"(?:세로형|가로형)\s*(?:영상|숏폼)?",
        r"\b(?:vertical|horizontal)\s*(?:format|video)?\b",
        r"\b(?:\d{1,3})\s*(?:초|seconds?|sec)\s*(?:분량|길이|영상)?",
        r"\b(?:\d{1,3})-second\b\s*(?:video|short)?",
        r"(?:숏폼\s*영상|세로\s*영상|가로\s*영상)\s*[.。]?",
        r"\b총\s*[.。]?",
        r"(?:마지막(?:\s*에)?\s*)?[^.。!?]*(?:텍스트\s*오버레이|오버레이\s*텍스트|텍스트\s*배치|자막|캡션|문구|글자|글씨)[^.。!?]*[.。!?]?",
        r"[^.。!?]*(?:text\s*overlay|overlay\s*text|subtitle|caption)[^.。!?]*[.。!?]?",
        r"실존\s*인물[^.。!?]*(?:브랜드\s*로고|저작권\s*캐릭터)[^.。!?]*[.。!?]?",
    ]
    for pattern in option_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[,，、]\s*", ", ", cleaned)
    cleaned = re.sub(r"(?:^\s*[,，、]\s*)|(?:\s*[,，、]\s*$)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _build_video_short_prompt(request: ResolvedVideoShortRequest) -> str:
    return request.final_prompt


def _build_video_short_prompt_fields(
    prompt: str,
    platform: str | None,
    aspect_ratio: str,
    duration_seconds: int,
    task: str = "textToVideo",
    has_start_frame: bool = False,
    has_last_frame: bool = False,
    has_reference_images: bool = False,
    metadata: dict[str, object] | None = None,
) -> str:
    platform_label = VIDEO_SHORT_PLATFORM_LABELS.get(platform or "", "short-form social media")
    metadata_platform_label = metadata.get("platformLabel") if metadata else None
    if isinstance(metadata_platform_label, str) and metadata_platform_label.strip():
        platform_label = metadata_platform_label

    user_scene_prompt = _strip_conflicting_video_prompt_options(prompt)
    format_instruction = (
        f"Create a {platform_label} video in {aspect_ratio} format. "
        "The video duration is controlled by the structured API parameter, so do not write duration wording in the prompt. "
        "Follow these format constraints exactly; ignore any conflicting duration, platform, or aspect-ratio wording in the scene description."
    )
    visual_direction = _build_video_input_direction(task, has_start_frame, has_last_frame, has_reference_images)
    if not user_scene_prompt:
        parts = [format_instruction]
    else:
        parts = [format_instruction, f"Scene description:\n{user_scene_prompt}"]
    if visual_direction:
        parts.append(visual_direction)
    parts.append(_video_visible_writing_policy())
    return append_visual_safety_guardrails("\n\n".join(parts))


def _video_visible_writing_policy() -> str:
    return (
        "[Visible writing policy]\n"
        "If visible words, signage, labels, menus, posters, banners, stickers, packaging text, subtitles, captions, "
        "overlays, or UI-like marks naturally appear in the video, render them only as short, common English words "
        "using English alphabet characters only. Non-English writing must not appear. Avoid Korean, Japanese, Chinese, "
        "Arabic, pseudo-text, unreadable glyphs, and symbols that resemble writing."
    )


def _build_video_input_direction(
    task: str,
    has_start_frame: bool,
    has_last_frame: bool,
    has_reference_images: bool,
) -> str | None:
    if task == "imageToVideo" and has_start_frame and has_last_frame:
        return (
            "First and last frame direction:\n"
            "- Use the provided image as the exact opening frame and the provided lastFrame as the exact ending frame.\n"
            "- Generate the middle of the video as a coherent transition that strongly follows the scene description.\n"
            "- Treat the scene description as the primary creative direction for location, subject, action, props, mood, and camera movement.\n"
            "- Preserve the first and last frames as temporal anchors, but make the intervening motion and visual storytelling reflect the scene description."
        )
    if task == "imageToVideo" and has_start_frame:
        return (
            "Start frame direction:\n"
            "- Use the provided image as the exact opening frame.\n"
            "- Animate outward from that frame while strongly following the scene description for location, subject, action, props, mood, and camera movement."
        )
    if task == "referenceToVideo" and has_reference_images:
        return (
            "Reference image direction:\n"
            "- Use the reference images as visual guidance for style, composition, color, and subject consistency.\n"
            "- The scene description remains the primary creative direction for the generated video."
        )
    return None


def _generate_video_short_with_fallback_sync(request: ResolvedVideoShortRequest) -> tuple[bytes, str, str, bool, list[str]]:
    candidates = deserialize_video_candidates(request.provider_candidates)
    if not candidates:
        candidates = [type("_Candidate", (), {"rank": 1, "provider": request.provider, "model": request.provider_model})()]
    warnings: list[str] = []
    last_error: Exception | None = None
    retryable_error: Exception | None = None
    for candidate in candidates:
        candidate_request = request.model_copy(
            update={
                "provider": candidate.provider,
                "provider_model": candidate.model,
            }
        )
        try:
            if candidate.provider == "google":
                video_bytes = _generate_video_short_sync(candidate_request)
            elif candidate.provider == "runway":
                video_bytes = generate_runway_video_short_sync(candidate_request, candidate.model)
            else:
                raise RequestValidationError(f"Unsupported video provider: {candidate.provider}")
            return video_bytes, candidate.provider, candidate.model, candidate.rank != 1, warnings
        except RequestValidationError:
            raise
        except Exception as exc:
            last_error = _normalize_video_provider_exception(exc) if candidate.provider == "google" else exc
            if candidate.provider == "google" and not _should_fallback_from_google_video_error(last_error):
                raise last_error
            if is_retryable_job_exception(last_error):
                retryable_error = last_error
            logger.warning(
                "Video provider candidate failed rank=%s provider=%s model=%s: %s",
                candidate.rank,
                candidate.provider,
                candidate.model,
                last_error,
            )
            warnings.append(
                f"Rank {candidate.rank} {candidate.provider}/{candidate.model} failed: {provider_warning_message(last_error)}"
            )
    if retryable_error and get_settings().celery_task_retry_enabled:
        raise retryable_error
    if last_error:
        raise last_error
    raise RuntimeError("No video provider candidates were available")


def _should_fallback_from_google_video_error(exc: Exception) -> bool:
    if isinstance(exc, (ProviderTimeoutError, TimeoutError)):
        return False
    return True


def _generate_video_short_sync(request: ResolvedVideoShortRequest) -> bytes:
    from google.genai import types

    settings = get_settings()
    validate_google_video_model(request.provider_model, settings)

    client = build_google_video_client(settings, request.provider_model)
    kwargs = _build_video_short_generate_kwargs(request, types)
    operation = client.models.generate_videos(**kwargs)
    if operation is None:
        raise RuntimeError("Video short generation did not return an operation")

    deadline = time.monotonic() + settings.video_max_wait_sec
    while not _is_operation_done(operation, "Video short"):
        if time.monotonic() > deadline:
            raise TimeoutError("Video short generation timed out")
        time.sleep(settings.video_poll_interval_sec)
        operation = client.operations.get(operation)
        if operation is None:
            raise RuntimeError("Video short polling returned an empty operation")

    return _extract_generated_video_bytes(operation, "Video short")


def _build_video_short_generate_kwargs(request: ResolvedVideoShortRequest, types_module):
    config_kwargs = {
        "number_of_videos": request.sample_count,
        "duration_seconds": request.duration_seconds,
        "aspect_ratio": request.aspect_ratio,
        "resolution": request.resolution,
        "seed": request.seed,
        "negative_prompt": request.negative_prompt,
        "person_generation": request.person_generation,
        "enhance_prompt": request.enhance_prompt,
        "compression_quality": request.compression_quality,
        "resize_mode": request.resize_mode,
        "output_gcs_uri": request.storage_uri,
        "pubsub_topic": request.pubsub_topic,
    }
    if request.generate_audio is False:
        config_kwargs["generate_audio"] = False
    if request.input and request.input.last_frame:
        config_kwargs["last_frame"] = _to_google_image(request.input.last_frame, types_module)
    if request.input and request.input.reference_images:
        config_kwargs["reference_images"] = [
            types_module.VideoGenerationReferenceImage(
                image=_to_google_image(reference, types_module),
                reference_type="asset",
            )
            for reference in request.input.reference_images
        ]

    kwargs = {
        "model": request.provider_model,
        "prompt": _build_video_short_prompt(request),
        "config": types_module.GenerateVideosConfig(
            **{key: value for key, value in config_kwargs.items() if value is not None}
        ),
    }
    if request.input and request.input.image:
        kwargs["image"] = _to_google_image(request.input.image, types_module)
    return kwargs


def _build_legacy_video_prompt(prompt: str) -> str:
    scene_prompt = _strip_conflicting_video_prompt_options(prompt)
    parts = []
    if scene_prompt:
        parts.append(scene_prompt)
    parts.append(
        "The video duration is controlled by the structured API parameter, so do not write duration wording in the prompt."
    )
    parts.append(_video_visible_writing_policy())
    return append_visual_safety_guardrails("\n\n".join(parts))


def _to_google_image(media: VideoShortMediaInput, types_module):
    settings = get_settings()
    if media is None:
        raise RequestValidationError("Video short media input is required")
    if media.gcs_uri:
        return types_module.Image(gcs_uri=media.gcs_uri, mime_type=media.mime_type)
    if not media.bytes_base64_encoded:
        raise RequestValidationError("Video short media input requires bytesBase64Encoded when gcsUri is omitted")
    image_bytes = decode_limited_base64(
        media.bytes_base64_encoded,
        max_bytes=settings.max_video_input_image_bytes,
        label="Video input image",
    )
    return types_module.Image(
        image_bytes=image_bytes,
        mime_type=media.mime_type,
    )


def _generate_veo_video_sync(request: VideoRequest) -> bytes:
    from google.genai import types

    settings = get_settings()
    validate_google_video_model(request.model, settings)

    client = build_google_video_client(settings, request.model)
    operation = client.models.generate_videos(
        model=request.model,
        prompt=_build_legacy_video_prompt(request.prompt),
        config=types.GenerateVideosConfig(
            number_of_videos=1,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
        ),
    )
    if operation is None:
        raise RuntimeError("Veo video generation did not return an operation")

    deadline = time.monotonic() + settings.video_max_wait_sec
    while not _is_operation_done(operation, "Veo"):
        if time.monotonic() > deadline:
            raise TimeoutError("Veo video generation timed out")
        time.sleep(settings.video_poll_interval_sec)
        operation = client.operations.get(operation)
        if operation is None:
            raise RuntimeError("Veo polling returned an empty operation")

    return _extract_generated_video_bytes(operation, "Veo")


def _is_operation_done(operation, label: str) -> bool:
    done = getattr(operation, "done", None)
    if done is None:
        return False
    return bool(done)


def _extract_generated_video_bytes(operation, label: str) -> bytes:
    error = getattr(operation, "error", None)
    if error:
        raise RuntimeError(f"{label} operation failed: {error}")

    response = getattr(operation, "response", None) or getattr(operation, "result", None)
    if response is None:
        raise RuntimeError(f"{label} operation did not include a response")
    generated_videos = getattr(response, "generated_videos", None) or []
    if not generated_videos:
        raise RuntimeError(f"{label} response did not include generated videos")

    first_generated_video = generated_videos[0]
    if first_generated_video is None:
        raise RuntimeError(f"{label} response included an empty generated video")

    video = getattr(first_generated_video, "video", None)
    if video is None:
        raise RuntimeError(f"{label} generated video did not include video data")

    video_bytes = getattr(video, "video_bytes", None)
    if video_bytes:
        return video_bytes

    video_uri = getattr(video, "uri", None)
    if video_uri:
        raise RuntimeError(f"{label} returned a URI instead of bytes: {video_uri}")
    raise RuntimeError(f"{label} generated video had no bytes")
