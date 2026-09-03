def test_video_short_resolves_defaults_and_google_kwargs_exclude_external_fields():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.veo_service import _build_video_short_generate_kwargs, resolve_video_short_request

    class FakeTypes:
        class Image:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class VideoGenerationReferenceImage:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class GenerateVideosConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    create_request = VideoShortCreateRequest(
        jobId="test-short-job-2",
        model="fast",
        prompt="A product short",
        aspectRatio="9:16",
        durationSeconds=8,
        input={
            "image": {"gcsUri": "gs://bucket/start.png", "mimeType": "image/png"},
            "lastFrame": {"gcsUri": "gs://bucket/end.png", "mimeType": "image/png"},
        },
        platform="tiktok",
        metadata={"campaignId": "campaign-1"},
    )
    request = resolve_video_short_request(create_request)

    kwargs = _build_video_short_generate_kwargs(request, FakeTypes)
    config = kwargs["config"].kwargs

    assert kwargs["model"] == "veo-3.1-fast-generate-001"
    assert kwargs["image"].kwargs["gcs_uri"] == "gs://bucket/start.png"
    assert config["last_frame"].kwargs["gcs_uri"] == "gs://bucket/end.png"
    assert config["number_of_videos"] == 1
    assert config["resolution"] == "720p"
    assert "fps" not in config
    assert config["enhance_prompt"] is True
    assert "generate_audio" not in config
    assert config["compression_quality"] == "optimized"
    assert config["resize_mode"] == "crop"
    assert "metadata" not in config
    assert "platform" not in config
    assert "[GAIM 시각 콘텐츠 안전 정책]" in kwargs["prompt"]
    assert "비성적, 비폭력적, 비혐오적" in kwargs["prompt"]
    assert "[Visible writing policy]" in kwargs["prompt"]
    assert "render them only as short, common English words" in kwargs["prompt"]
    assert "Korean writing must not appear" in kwargs["prompt"]
    assert "8-second" not in kwargs["prompt"]
    assert "First and last frame direction:" in kwargs["prompt"]
    assert "provided image as the exact opening frame" in kwargs["prompt"]
    assert "provided lastFrame as the exact ending frame" in kwargs["prompt"]
    assert "scene description as the primary creative direction" in kwargs["prompt"]
    assert "A product short" in kwargs["prompt"]

def test_video_short_google_kwargs_include_generate_audio_only_when_false():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.veo_service import _build_video_short_generate_kwargs, resolve_video_short_request

    class FakeTypes:
        class GenerateVideosConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    create_request = VideoShortCreateRequest(
        jobId="test-short-audio-off",
        model="fast",
        prompt="A silent product short",
        aspectRatio="9:16",
        durationSeconds=4,
        task="textToVideo",
        advanced={"generateAudio": False},
    )
    request = resolve_video_short_request(create_request)

    kwargs = _build_video_short_generate_kwargs(request, FakeTypes)

    assert kwargs["config"].kwargs["generate_audio"] is False

def test_video_short_default_candidates_keep_veo_first_and_runway_fallback():
    from app.services.video.model_router import build_video_short_candidates

    fast_candidates = build_video_short_candidates("fast", "imageToVideo")
    assert [(item.provider, item.model) for item in fast_candidates] == [
        ("google", "veo-3.1-fast-generate-001"),
        ("runway", "gen4_turbo"),
    ]

    text_candidates = build_video_short_candidates("fast", "textToVideo")
    assert [(item.provider, item.model) for item in text_candidates] == [
        ("google", "veo-3.1-fast-generate-001"),
        ("runway", "gen4.5"),
    ]

    standard_candidates = build_video_short_candidates("standard")
    assert [(item.provider, item.model) for item in standard_candidates] == [
        ("google", "veo-3.1-generate-001"),
        ("runway", "gen4.5"),
    ]

def test_video_short_provider_override_selects_runway_only():
    from app.services.video.model_router import build_video_short_candidates

    candidates = build_video_short_candidates("standard", provider_override="runway")

    assert [(item.provider, item.model) for item in candidates] == [("runway", "gen4.5")]

def test_video_short_provider_override_selects_runway_model_by_task():
    from app.services.video.model_router import build_video_short_candidates

    text_candidates = build_video_short_candidates("fast", "textToVideo", provider_override="runway")
    image_candidates = build_video_short_candidates("fast", "imageToVideo", provider_override="runway")

    assert [(item.provider, item.model) for item in text_candidates] == [("runway", "gen4.5")]
    assert [(item.provider, item.model) for item in image_candidates] == [("runway", "gen4_turbo")]

def test_video_short_reference_to_video_uses_standard_model_and_eight_seconds():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.veo_service import resolve_video_short_request

    request = resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="reference-policy-job",
            prompt="레퍼런스 이미지를 참고한 숏폼",
            model="fast",
            platform="instagram_reels",
            task="referenceToVideo",
            aspectRatio="9:16",
            durationSeconds=4,
            input={
                "referenceImages": [
                    {
                        "bytesBase64Encoded": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                        "mimeType": "image/png",
                    }
                ]
            },
        )
    )

    assert request.provider == "google"
    assert request.provider_model == "veo-3.1-generate-001"
    assert request.duration_seconds == 8

def test_video_short_generation_falls_back_to_runway_when_veo_is_unavailable(monkeypatch):
    from app.core.exceptions import ProviderServiceUnavailableError
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service

    def fail_google(request):
        raise ProviderServiceUnavailableError("Google provider is temporarily unavailable.")

    def succeed_runway(request, model):
        assert model == "gen4.5"
        return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"

    monkeypatch.setattr(veo_service, "_generate_video_short_sync", fail_google)
    monkeypatch.setattr(veo_service, "generate_runway_video_short_sync", succeed_runway)

    request = veo_service.resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="fallback-video-job",
            prompt="강릉 카페 홍보 영상",
            model="fast",
            platform="instagram_reels",
            task="textToVideo",
            aspectRatio="9:16",
            durationSeconds=8,
        )
    )

    video_bytes, provider, model_used, fallback_used, warnings = veo_service._generate_video_short_with_fallback_sync(
        request
    )

    assert video_bytes.startswith(b"\x00\x00\x00\x18ftyp")
    assert provider == "runway"
    assert model_used == "gen4.5"
    assert fallback_used is True
    assert "google/veo-3.1-fast-generate-001 failed" in warnings[0]

def test_video_short_timeout_does_not_fallback_to_runway(monkeypatch):
    from app.core.exceptions import ProviderTimeoutError
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service

    def timeout_google(request):
        raise ProviderTimeoutError("Google provider request timed out.")

    def fail_if_runway_called(request, model):
        raise AssertionError("Runway should not run after Google long polling timeout")

    monkeypatch.setattr(veo_service, "_generate_video_short_sync", timeout_google)
    monkeypatch.setattr(veo_service, "generate_runway_video_short_sync", fail_if_runway_called)

    request = veo_service.resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="retry-video-job",
            prompt="강릉 카페 홍보 영상",
            model="fast",
            platform="instagram_reels",
            task="textToVideo",
            aspectRatio="9:16",
            durationSeconds=8,
        )
    )

    try:
        veo_service._generate_video_short_with_fallback_sync(request)
    except ProviderTimeoutError:
        pass
    else:
        raise AssertionError("Expected Google timeout to fail without Runway fallback")

def test_video_short_request_error_from_google_api_falls_back_to_runway(monkeypatch):
    from app.core.exceptions import ProviderRequestError
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service

    def fail_google_not_found(request):
        raise ProviderRequestError("Google Veo model was not found.")

    def succeed_runway(request, model):
        return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"

    monkeypatch.setattr(veo_service, "_generate_video_short_sync", fail_google_not_found)
    monkeypatch.setattr(veo_service, "generate_runway_video_short_sync", succeed_runway)

    request = veo_service.resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="not-found-fallback-video-job",
            prompt="강릉 카페 홍보 영상",
            model="fast",
            platform="instagram_reels",
            task="textToVideo",
            aspectRatio="9:16",
            durationSeconds=8,
        )
    )

    video_bytes, provider, model_used, fallback_used, warnings = veo_service._generate_video_short_with_fallback_sync(
        request
    )

    assert video_bytes.startswith(b"\x00\x00\x00\x18ftyp")
    assert provider == "runway"
    assert model_used == "gen4.5"
    assert fallback_used is True
    assert "provider rejected the request" in warnings[0]

def test_video_short_validation_error_does_not_fallback_to_runway(monkeypatch):
    from app.core.exceptions import RequestValidationError
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service

    def fail_google_validation(request):
        raise RequestValidationError("Bad video input.")

    def fail_if_runway_called(request, model):
        raise AssertionError("Runway should not run after validation failure")

    monkeypatch.setattr(veo_service, "_generate_video_short_sync", fail_google_validation)
    monkeypatch.setattr(veo_service, "generate_runway_video_short_sync", fail_if_runway_called)

    request = veo_service.resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="validation-video-job",
            prompt="강릉 카페 홍보 영상",
            model="fast",
            platform="instagram_reels",
            task="textToVideo",
            aspectRatio="9:16",
            durationSeconds=8,
        )
    )

    try:
        veo_service._generate_video_short_with_fallback_sync(request)
    except RequestValidationError:
        pass
    else:
        raise AssertionError("Expected validation error to fail without Runway fallback")

def test_runway_payload_preserves_supported_video_duration():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.runway_service import _build_runway_payload
    from app.services.video.veo_service import resolve_video_short_request

    for duration in (4, 6, 8):
        request = resolve_video_short_request(
            VideoShortCreateRequest(
                jobId=f"runway-duration-{duration}",
                prompt="강릉 카페 홍보 영상",
                model="fast",
                providerOverride="runway",
                platform="instagram_reels",
                task="textToVideo",
                aspectRatio="9:16",
                durationSeconds=duration,
            )
        )

        payload = _build_runway_payload(request, "gen4.5")

        assert payload["duration"] == duration

def test_video_extract_generated_video_bytes_rejects_empty_response():
    from types import SimpleNamespace

    from app.services.video.veo_service import _extract_generated_video_bytes

    operation = SimpleNamespace(error=None, response=SimpleNamespace(generated_videos=[]), result=None)

    try:
        _extract_generated_video_bytes(operation, "Veo")
    except RuntimeError as exc:
        assert "did not include generated videos" in str(exc)
    else:
        raise AssertionError("Expected empty generated videos to fail")

def test_video_operation_done_none_is_treated_as_pending():
    from types import SimpleNamespace

    from app.services.video.veo_service import _is_operation_done

    assert _is_operation_done(SimpleNamespace(done=None), "Veo") is False

def test_video_extract_generated_video_bytes_rejects_missing_video_data():
    from types import SimpleNamespace

    from app.services.video.veo_service import _extract_generated_video_bytes

    operation = SimpleNamespace(
        error=None,
        response=SimpleNamespace(generated_videos=[SimpleNamespace(video=None)]),
        result=None,
    )

    try:
        _extract_generated_video_bytes(operation, "Video short")
    except RuntimeError as exc:
        assert "did not include video data" in str(exc)
    else:
        raise AssertionError("Expected missing video data to fail")

def test_video_to_google_image_rejects_invalid_base64():
    from types import SimpleNamespace

    from app.core.exceptions import RequestValidationError
    from app.schemas.video import VideoShortMediaInput
    from app.services.video.veo_service import _to_google_image

    media = VideoShortMediaInput(bytesBase64Encoded="not-valid-base64", mimeType="image/png")
    fake_types = SimpleNamespace(Image=lambda **kwargs: kwargs)

    try:
        _to_google_image(media, fake_types)
    except RequestValidationError as exc:
        assert "not valid base64" in exc.message
    else:
        raise AssertionError("Expected invalid base64 media to fail")
