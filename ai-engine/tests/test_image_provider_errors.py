def test_provider_error_classification_marks_rate_limit_retryable():
    from app.core.exceptions import ProviderRateLimitError
    from app.core.provider_errors import classify_openai_exception

    class FakeRateLimitError(Exception):
        status_code = 429

    classified = classify_openai_exception(FakeRateLimitError("api key sk-secret leaked detail"))

    assert isinstance(classified, ProviderRateLimitError)
    assert classified.retryable is True
    assert "sk-secret" not in classified.message

def test_image_create_warning_does_not_expose_raw_exception(monkeypatch):
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def fail_google(request):
        raise RuntimeError("raw provider detail token=secret-value")

    monkeypatch.setattr(create_service, "generate_google_images", fail_google)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    import asyncio

    result = asyncio.run(create_service.create_image(request))
    warnings_text = "\n".join(result.routing.warnings)

    assert "secret-value" not in warnings_text
    assert "raw provider detail" not in warnings_text
    assert "unexpected provider failure" in warnings_text

def test_image_create_auth_error_does_not_fallback(monkeypatch):
    import asyncio

    from app.core.exceptions import ProviderAuthenticationError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def fail_google_auth(request):
        raise ProviderAuthenticationError("Google provider authentication failed.")

    async def unexpected_openai_call(request):
        raise AssertionError("OpenAI fallback should not run after provider auth failure")

    monkeypatch.setattr(create_service, "generate_google_images", fail_google_auth)
    monkeypatch.setattr(create_service, "generate_openai_images", unexpected_openai_call)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    try:
        asyncio.run(create_service.create_image(request))
    except ProviderAuthenticationError:
        pass
    else:
        raise AssertionError("Expected provider authentication failure to bypass fallback")

def test_image_create_all_retryable_failures_use_placeholder_when_celery_retry_disabled(monkeypatch):
    import asyncio

    from app.core.exceptions import ProviderTimeoutError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def timeout_provider(request):
        raise ProviderTimeoutError("provider timed out")

    monkeypatch.setattr(create_service, "generate_google_images", timeout_provider)
    monkeypatch.setattr(create_service, "generate_openai_images", timeout_provider)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    result = asyncio.run(create_service.create_image(request))

    assert result.provider == "local"
    assert result.routing.fallback_used is True

def test_image_create_all_retryable_failures_are_retried_when_retry_enabled(monkeypatch):
    import asyncio

    from app.config import get_settings
    from app.core.exceptions import ProviderTimeoutError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def timeout_provider(request):
        raise ProviderTimeoutError("provider timed out")

    monkeypatch.setenv("CELERY_TASK_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(create_service, "generate_google_images", timeout_provider)
    monkeypatch.setattr(create_service, "generate_openai_images", timeout_provider)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    try:
        asyncio.run(create_service.create_image(request))
    except ProviderTimeoutError:
        pass
    else:
        raise AssertionError("Expected retryable provider failure instead of local placeholder")

def test_image_create_mixed_retryable_and_non_retryable_uses_placeholder_when_retry_enabled(monkeypatch):
    import asyncio

    from app.config import get_settings
    from app.core.exceptions import ProviderRequestError, ProviderTimeoutError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def timeout_google(request):
        raise ProviderTimeoutError("provider timed out")

    async def reject_openai(request):
        raise ProviderRequestError("provider rejected request")

    monkeypatch.setenv("CELERY_TASK_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(create_service, "generate_google_images", timeout_google)
    monkeypatch.setattr(create_service, "generate_openai_images", reject_openai)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    result = asyncio.run(create_service.create_image(request))

    assert result.provider == "local"
    assert result.routing.fallback_used is True

def test_image_job_failure_callback_uses_public_error(monkeypatch):
    from app.workers.tasks import image_tasks

    async def fail_create_image(request):
        raise RuntimeError("provider payload contained secret-value")

    captured = {}
    terminal_results = []

    async def fake_progress(job_id, progress):
        return None

    async def fake_failed(job_id, error_message, duration_ms=None):
        captured["job_id"] = job_id
        captured["error"] = error_message

    monkeypatch.setattr(image_tasks, "create_image", fail_create_image)
    monkeypatch.setattr(image_tasks, "notify_job_progress", fake_progress)
    monkeypatch.setattr(image_tasks, "notify_job_failed", fake_failed)
    monkeypatch.setattr(
        image_tasks,
        "record_terminal_status",
        lambda job_type, job_id, payload: terminal_results.append((job_type, job_id, payload)),
    )

    import asyncio

    result = asyncio.run(
        image_tasks._run_image_job(
            {
                "jobId": "job-safe-error",
                "purpose": "홍보",
                "channels": ["인스타"],
                "image_prompt": "카페 이미지",
                "visual_mood": "bright",
                "n": 1,
            }
        )
    )

    assert result["status"] == "failed"
    assert "secret-value" not in result["error"]
    assert "secret-value" not in captured["error"]
    assert captured["job_id"] == "job-safe-error"
    assert terminal_results[0][0] == "image"
    assert terminal_results[0][1] == "job-safe-error"
    assert terminal_results[0][2]["status"] == "failed"
    assert terminal_results[0][2]["progressPct"] == 100

def test_image_job_completed_records_fallback_metadata(monkeypatch):
    import asyncio

    from app.schemas.image import ImageCreateResponse, ImageCreateRouting, ImageModelCandidate
    from app.workers.tasks import image_tasks

    completed_callback = {}
    terminal_results = []

    candidate = ImageModelCandidate(
        rank=3,
        provider="local",
        model="local-placeholder",
        operation="placeholder",
        size="1024x1024",
        n=1,
        reason="All provider candidates failed.",
    )
    image_result = ImageCreateResponse(
        images=["http://testserver/generated/images/placeholder.png"],
        provider="local",
        model_used="local-placeholder",
        routing=ImageCreateRouting(
            primary_channel="instagram_feed",
            final_prompt="카페 이미지",
            selected_rank=3,
            selected=candidate,
            attempted_models=[candidate],
            fallback_used=True,
            warnings=["Provider generation failed or was unavailable."],
        ),
    )

    async def fake_create_image(request):
        return image_result

    async def fake_progress(job_id, progress):
        return True

    async def fake_completed(**kwargs):
        completed_callback.update(kwargs)
        return True

    monkeypatch.setattr(image_tasks, "create_image", fake_create_image)
    monkeypatch.setattr(image_tasks, "notify_job_progress", fake_progress)
    monkeypatch.setattr(image_tasks, "notify_image_job_completed", fake_completed)
    monkeypatch.setattr(
        image_tasks,
        "record_terminal_status",
        lambda job_type, job_id, payload: terminal_results.append((job_type, job_id, payload)),
    )

    result = asyncio.run(
        image_tasks._run_image_job(
            {
                "jobId": "job-image-fallback",
                "purpose": "홍보",
                "channels": ["인스타"],
                "image_prompt": "카페 이미지",
                "visual_mood": "bright",
                "n": 1,
            }
        )
    )

    assert result["status"] == "completed"
    assert result["fallbackUsed"] is True
    assert result["warnings"] == ["Provider generation failed or was unavailable."]
    assert completed_callback["fallback_used"] is True
    assert completed_callback["warnings"] == ["Provider generation failed or was unavailable."]
    assert terminal_results[0][2]["fallbackUsed"] is True
    assert terminal_results[0][2]["warnings"] == ["Provider generation failed or was unavailable."]

def test_video_job_public_error_message_does_not_expose_raw_exception():
    from app.core.provider_errors import classify_google_exception, public_job_error_message

    error = public_job_error_message(classify_google_exception(RuntimeError("uri=https://internal.example/secret")))

    assert "internal.example" not in error
    assert "secret" not in error
    assert "오류" in error or "외부 AI 서비스" in error
