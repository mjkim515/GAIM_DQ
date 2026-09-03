def test_google_vertex_auth_requires_service_account(monkeypatch):
    from app.config import Settings
    from app.services.image.google_service import _build_google_client
    from app.core.exceptions import ProviderError

    settings = Settings(google_auth_mode="vertex_ai", gcp_service_account_json="{}")
    try:
        _build_google_client(settings)
    except ProviderError as exc:
        assert "Google provider authentication failed" in str(exc)
        assert "GCP_SERVICE_ACCOUNT_JSON" not in str(exc)
    else:
        raise AssertionError("Expected ProviderError")

def test_production_settings_reject_eager_mode(monkeypatch):
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "production-secret")
    monkeypatch.setenv("WAS_INTERNAL_TOKEN", "production-token")
    monkeypatch.setenv("WAS_BASE_URL", "https://was.example.com")
    monkeypatch.setenv("AI_PROVIDER_MODE", "mock")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "CELERY_TASK_ALWAYS_EAGER must be false in production" in str(exc_info.value)

def test_google_client_uses_configured_timeout(monkeypatch):
    from app.config import get_settings
    from app.services.image.google_service import _build_google_client

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GOOGLE_PROVIDER_TIMEOUT_MS", "12345")
    get_settings.cache_clear()

    client = _build_google_client(get_settings(), "gemini-2.5-flash-image")

    assert client._api_client._http_options.timeout == 12345

def test_openai_image_client_uses_configured_timeout_and_closes(monkeypatch):
    import asyncio
    import sys
    from types import SimpleNamespace

    from app.config import get_settings
    from app.schemas.image import ProviderImageRequest
    from app.services.image.openai_service import generate_openai_images

    captured = {"timeout": None, "closed": False}

    class FakeImages:
        async def generate(self, **kwargs):
            return SimpleNamespace(data=[
                SimpleNamespace(b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=")
            ])

    class FakeAsyncOpenAI:
        def __init__(self, api_key, timeout):
            captured["timeout"] = timeout
            self.images = FakeImages()

        async def close(self):
            captured["closed"] = True

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    monkeypatch.setenv("AI_PROVIDER_MODE", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_PROVIDER_TIMEOUT_SEC", "12.5")
    get_settings.cache_clear()

    result = asyncio.run(generate_openai_images(ProviderImageRequest(
        prompt="timeout test",
        model="gpt-image-1.5",
        n=1,
    )))

    assert result.provider == "openai"
    assert captured["timeout"] == 12.5
    assert captured["closed"] is True

def test_reference_image_download_uses_configured_timeout(monkeypatch):
    from io import BytesIO

    from app.config import get_settings
    from app.services.image import references

    captured = {"timeout": None}

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url, timeout):
        captured["timeout"] = timeout
        return FakeResponse(b"image-bytes")

    monkeypatch.setattr(references, "urlopen", fake_urlopen)
    monkeypatch.setattr(references.socket, "getaddrinfo", lambda *args, **kwargs: [
        (None, None, None, None, ("93.184.216.34", 443)),
    ])
    monkeypatch.setenv("REFERENCE_IMAGE_DOWNLOAD_TIMEOUT_SEC", "7.5")
    get_settings.cache_clear()

    payload = references._load_from_url("https://example.com/reference.png")

    assert payload == b"image-bytes"
    assert captured["timeout"] == 7.5

def test_runway_requests_use_configured_timeouts(monkeypatch):
    from io import BytesIO

    from app.config import get_settings
    from app.services.video import runway_service

    captured = {"request_timeout": None, "download_timeout": None}

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(target, timeout):
        if hasattr(target, "full_url"):
            captured["request_timeout"] = timeout
            return FakeResponse(b'{"id":"task-1"}')
        captured["download_timeout"] = timeout
        return FakeResponse(b"video-bytes")

    monkeypatch.setattr(runway_service.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("RUNWAY_REQUEST_TIMEOUT_SEC", "8.5")
    monkeypatch.setenv("RUNWAY_DOWNLOAD_TIMEOUT_SEC", "9.5")
    get_settings.cache_clear()

    settings = get_settings()
    response = runway_service._runway_json_request("POST", "https://runway.test/task", {}, settings)
    video_bytes = runway_service._download_runway_output("https://runway.test/output.mp4")

    assert response == {"id": "task-1"}
    assert video_bytes == b"video-bytes"
    assert captured["request_timeout"] == 8.5
    assert captured["download_timeout"] == 9.5

def test_image_reference_base64_rejects_oversized_input(monkeypatch):
    import base64

    from app.config import get_settings
    from app.core.exceptions import RequestValidationError
    from app.schemas.image import ReferenceImage
    from app.services.image.references import load_reference_image_bytes

    monkeypatch.setenv("MAX_IMAGE_REFERENCE_BYTES", "4")
    get_settings.cache_clear()

    reference = ReferenceImage(
        b64_json=base64.b64encode(b"12345").decode("ascii"),
        mime_type="image/png",
    )

    try:
        load_reference_image_bytes(reference)
    except RequestValidationError as exc:
        assert "Image reference exceeds" in exc.message
    else:
        raise AssertionError("Expected oversized image reference to fail")

def test_image_reference_local_url_rejects_oversized_file(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.core.exceptions import RequestValidationError
    from app.schemas.image import ReferenceImage
    from app.services.image.references import load_reference_image_bytes

    image_path = tmp_path / "storage" / "images" / "large.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"12345")
    monkeypatch.setenv("STORAGE_BASE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("STORAGE_PUBLIC_BASE_URL", "http://testserver/generated")
    monkeypatch.setenv("MAX_IMAGE_REFERENCE_BYTES", "4")
    get_settings.cache_clear()

    reference = ReferenceImage(
        image_url="http://testserver/generated/images/large.png",
        mime_type="image/png",
    )

    try:
        load_reference_image_bytes(reference)
    except RequestValidationError as exc:
        assert "Image reference exceeds" in exc.message
    else:
        raise AssertionError("Expected oversized local image reference to fail")

def test_video_input_image_base64_rejects_oversized_input(monkeypatch):
    import base64
    from types import SimpleNamespace

    from app.config import get_settings
    from app.core.exceptions import RequestValidationError
    from app.schemas.video import VideoShortMediaInput
    from app.services.video.veo_service import _to_google_image

    monkeypatch.setenv("MAX_VIDEO_INPUT_IMAGE_BYTES", "4")
    get_settings.cache_clear()
    media = VideoShortMediaInput(
        bytesBase64Encoded=base64.b64encode(b"12345").decode("ascii"),
        mimeType="image/png",
    )
    fake_types = SimpleNamespace(Image=lambda **kwargs: kwargs)

    try:
        _to_google_image(media, fake_types)
    except RequestValidationError as exc:
        assert "Video input image exceeds" in exc.message
    else:
        raise AssertionError("Expected oversized video input image to fail")
