def test_video_short_duplicate_job_id_is_not_enqueued_twice(monkeypatch):
    import asyncio

    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service
    from app.workers.tasks import video_tasks

    job_id = "duplicate-video-job"
    veo_service._JOBS.pop(job_id, None)
    veo_service._JOB_UPDATED_AT.pop(job_id, None)
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(video_tasks.generate_video_short_task, "apply_async", capture_enqueue)
    request = VideoShortCreateRequest.model_validate({
        "jobId": job_id,
        "prompt": "A single video should be generated",
        "model": "fast",
        "task": "textToVideo",
        "aspectRatio": "9:16",
        "durationSeconds": 4,
    })

    async def enqueue_twice():
        first_response = await veo_service.enqueue_video_short_generation(request)
        second_response = await veo_service.enqueue_video_short_generation(request)
        return first_response, second_response

    first, second = asyncio.run(enqueue_twice())

    assert first.status.value == "queued"
    assert second.status.value == "queued"
    assert "이미 등록된 jobId" in second.message
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "video-queue"

def test_video_short_expired_job_id_can_be_enqueued_again(monkeypatch):
    import asyncio
    import time

    from app.schemas.common import JobStatus
    from app.schemas.video import VideoShortCreateRequest, VideoStatusResponse
    from app.services.video import veo_service
    from app.workers.tasks import video_tasks

    job_id = "expired-video-job"
    veo_service._JOBS[job_id] = VideoStatusResponse(
        job_id=job_id,
        status=JobStatus.queued,
        progress_pct=0,
    )
    veo_service._JOB_UPDATED_AT[job_id] = time.time() - veo_service.VIDEO_JOB_TTL_SECONDS - 1
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(video_tasks.generate_video_short_task, "apply_async", capture_enqueue)
    request = VideoShortCreateRequest.model_validate({
        "jobId": job_id,
        "prompt": "An expired video job id should enqueue again",
        "model": "fast",
        "task": "textToVideo",
        "aspectRatio": "9:16",
        "durationSeconds": 4,
    })

    response = asyncio.run(veo_service.enqueue_video_short_generation(request))

    assert response.status.value == "queued"
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "video-queue"
    assert job_id in veo_service._JOBS
    assert job_id in veo_service._JOB_UPDATED_AT

def test_image_duplicate_job_id_is_not_enqueued_twice(monkeypatch):
    import asyncio

    from app.api.v1 import image as image_api
    from app.schemas.image import ImageJobRequest

    job_id = "duplicate-image-job"
    image_api._IMAGE_JOB_IDS.pop(job_id, None)
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(image_api.generate_image_task, "apply_async", capture_enqueue)
    request = ImageJobRequest.model_validate({
        "jobId": job_id,
        "purpose": "promotion",
        "channels": ["instagram"],
        "image_prompt": "A single image should be generated",
        "n": 1,
    })

    async def enqueue_twice():
        first_response = await image_api.enqueue_image_job_endpoint(request)
        second_response = await image_api.enqueue_image_job_endpoint(request)
        return first_response, second_response

    first, second = asyncio.run(enqueue_twice())

    assert first.status == "queued"
    assert second.status == "queued"
    assert "이미 등록된 jobId" in second.message
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "image-queue"

def test_image_expired_job_id_can_be_enqueued_again(monkeypatch):
    import asyncio
    import time

    from app.api.v1 import image as image_api
    from app.schemas.image import ImageJobRequest

    job_id = "expired-image-job"
    image_api._IMAGE_JOB_IDS[job_id] = time.time() - image_api.IMAGE_JOB_ID_TTL_SECONDS - 1
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(image_api.generate_image_task, "apply_async", capture_enqueue)
    request = ImageJobRequest.model_validate({
        "jobId": job_id,
        "purpose": "promotion",
        "channels": ["instagram"],
        "image_prompt": "An expired image job id should enqueue again",
        "n": 1,
    })

    response = asyncio.run(image_api.enqueue_image_job_endpoint(request))

    assert response.status == "queued"
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "image-queue"
    assert job_id in image_api._IMAGE_JOB_IDS

def test_video_completed_callback_includes_provider_metadata(monkeypatch):
    from app.services import callbacks

    captured = {}

    async def fake_post_callback(path, payload):
        captured["path"] = path
        captured["payload"] = payload

    monkeypatch.setattr(callbacks, "_post_callback", fake_post_callback)

    import asyncio

    asyncio.run(
        callbacks.notify_job_completed(
            job_id="video-callback-metadata",
            result_url="http://localhost:8000/generated/videos/result.mp4",
            duration_ms=1234,
            provider="google",
            model_used="veo-3.1-fast-generate-001",
            fallback_used=False,
            warnings=[],
        )
    )

    assert captured["path"] == "/internal/callback/jobs/video-callback-metadata"
    assert captured["payload"]["status"] == "completed"
    assert captured["payload"]["provider"] == "google"
    assert captured["payload"]["modelUsed"] == "veo-3.1-fast-generate-001"
    assert captured["payload"]["fallbackUsed"] is False
    assert captured["payload"]["warnings"] == []

def test_image_completed_callback_includes_fallback_metadata(monkeypatch):
    from app.services import callbacks

    captured = {}

    async def fake_post_callback(path, payload):
        captured["path"] = path
        captured["payload"] = payload

    monkeypatch.setattr(callbacks, "_post_callback", fake_post_callback)

    import asyncio

    asyncio.run(
        callbacks.notify_image_job_completed(
            job_id="image-callback-metadata",
            images=["http://localhost:8000/generated/images/result.png"],
            provider="local",
            model_used="local-placeholder",
            duration_ms=1234,
            fallback_used=True,
            warnings=["Provider generation failed or was unavailable."],
        )
    )

    assert captured["path"] == "/internal/callback/jobs/image-callback-metadata"
    assert captured["payload"]["status"] == "completed"
    assert captured["payload"]["provider"] == "local"
    assert captured["payload"]["modelUsed"] == "local-placeholder"
    assert captured["payload"]["fallbackUsed"] is True
    assert captured["payload"]["warnings"] == ["Provider generation failed or was unavailable."]

def test_video_task_result_remembers_terminal_status(monkeypatch):
    from app.schemas.common import JobStatus
    from app.schemas.video import VideoStatusResponse
    from app.services.video import veo_service

    terminal_results = []
    monkeypatch.setattr(
        veo_service,
        "record_terminal_status",
        lambda job_type, job_id, payload: terminal_results.append((job_type, job_id, payload)),
    )

    result = veo_service._video_task_result(
        VideoStatusResponse(
            job_id="video-terminal-job",
            status=JobStatus.completed,
            video_url="http://testserver/generated/videos/result.mp4",
            progress_pct=100,
        ),
        2345,
        {"completed": False},
    )

    assert result["status"] == "completed"
    assert terminal_results[0][0] == "video"
    assert terminal_results[0][1] == "video-terminal-job"
    assert terminal_results[0][2]["videoUrl"] == "http://testserver/generated/videos/result.mp4"
    assert terminal_results[0][2]["callbacks"] == {"completed": False}

def test_retryable_provider_error_is_not_retried_by_default(monkeypatch):
    from types import SimpleNamespace

    from app.core.exceptions import ProviderTimeoutError, RequestValidationError
    from app.workers.tasks import image_tasks

    task = SimpleNamespace(request=SimpleNamespace(retries=0), max_retries=2)
    exhausted_task = SimpleNamespace(request=SimpleNamespace(retries=2), max_retries=2)

    assert image_tasks._should_retry(task, ProviderTimeoutError("timeout")) is False
    assert image_tasks._should_retry(exhausted_task, ProviderTimeoutError("timeout")) is False
    assert image_tasks._should_retry(task, RequestValidationError("bad request")) is False

def test_retryable_provider_error_is_marked_for_celery_retry_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from app.config import get_settings
    from app.core.exceptions import ProviderTimeoutError, RequestValidationError
    from app.workers.tasks import image_tasks

    monkeypatch.setenv("CELERY_TASK_RETRY_ENABLED", "true")
    get_settings.cache_clear()

    task = SimpleNamespace(request=SimpleNamespace(retries=0), max_retries=2)
    exhausted_task = SimpleNamespace(request=SimpleNamespace(retries=2), max_retries=2)

    assert image_tasks._should_retry(task, ProviderTimeoutError("timeout")) is True
    assert image_tasks._should_retry(exhausted_task, ProviderTimeoutError("timeout")) is False
    assert image_tasks._should_retry(task, RequestValidationError("bad request")) is False

def test_celery_delivery_settings_are_configured():
    from app.workers.celery_app import celery_app

    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.task_acks_on_failure_or_timeout is True

def test_provider_time_limits_are_aligned_with_celery_limits():
    from app.config import get_settings

    settings = get_settings()

    assert settings.video_max_wait_sec < settings.celery_task_soft_time_limit
    assert settings.celery_task_soft_time_limit < settings.celery_task_time_limit
    assert settings.celery_task_time_limit < settings.celery_broker_visibility_timeout

def test_worker_job_lock_duplicate_skips_run(monkeypatch):
    from app.workers import job_locks

    called = {"run": False}

    def fail_if_called():
        called["run"] = True
        return {"status": "ran"}

    monkeypatch.setattr(job_locks, "acquire_job_lock", lambda job_id, job_type, task_id=None: None)

    result = job_locks.run_with_job_lock(
        job_id="duplicate-job",
        job_type="image",
        on_duplicate=lambda: {"status": "duplicate_skipped"},
        run=fail_if_called,
    )

    assert result == {"status": "duplicate_skipped"}
    assert called["run"] is False

def test_image_task_passes_celery_task_id_to_job_lock(monkeypatch):
    from app.workers.tasks import image_tasks

    captured = {}

    def fake_run_with_job_lock(**kwargs):
        captured.update(kwargs)
        return {"status": "captured"}

    monkeypatch.setattr(image_tasks, "run_with_job_lock", fake_run_with_job_lock)

    image_tasks.generate_image_task.push_request(id="image-task-id")
    try:
        result = image_tasks.generate_image_task.run({"jobId": "image-job-id"})
    finally:
        image_tasks.generate_image_task.pop_request()

    assert result == {"status": "captured"}
    assert captured["job_id"] == "image-job-id"
    assert captured["job_type"] == "image"
    assert captured["task_id"] == "image-task-id"

def test_video_tasks_pass_celery_task_id_to_job_lock(monkeypatch):
    from app.workers.tasks import video_tasks

    captured = []

    def fake_run_with_job_lock(**kwargs):
        captured.append(kwargs)
        return {"status": "captured"}

    monkeypatch.setattr(video_tasks, "run_with_job_lock", fake_run_with_job_lock)

    video_tasks.generate_video_task.push_request(id="video-task-id")
    try:
        video_result = video_tasks.generate_video_task.run({"jobId": "video-job-id"})
    finally:
        video_tasks.generate_video_task.pop_request()

    video_tasks.generate_video_short_task.push_request(id="video-short-task-id")
    try:
        short_result = video_tasks.generate_video_short_task.run({"jobId": "video-short-job-id"})
    finally:
        video_tasks.generate_video_short_task.pop_request()

    assert video_result == {"status": "captured"}
    assert short_result == {"status": "captured"}
    assert captured[0]["job_id"] == "video-job-id"
    assert captured[0]["job_type"] == "video"
    assert captured[0]["task_id"] == "video-task-id"
    assert captured[1]["job_id"] == "video-short-job-id"
    assert captured[1]["job_type"] == "video-short"
    assert captured[1]["task_id"] == "video-short-task-id"

def test_video_task_result_does_not_include_request_payload(monkeypatch):
    from app.workers.tasks import video_tasks

    async def fake_generation(job_id, request):
        return {
            "jobId": job_id,
            "status": "completed",
            "videoUrl": "http://testserver/generated/videos/result.mp4",
            "callbacks": {},
        }

    monkeypatch.setattr(video_tasks, "_run_live_video_generation", fake_generation)

    result = video_tasks._run_video_generation(
        {
            "jobId": "video-result-payload",
            "prompt": "A small video",
            "model": "fast",
            "durationSeconds": 4,
            "aspectRatio": "16:9",
            "metadata": {"largeInput": "x" * 1000},
        }
    )

    assert result["status"] == "completed"
    assert "request" not in result
