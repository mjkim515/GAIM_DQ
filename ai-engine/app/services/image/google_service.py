import asyncio
import logging

from app.config import get_settings
from app.core.exceptions import ProviderAuthenticationError, ProviderError, ProviderRequestError
from app.core.provider_errors import classify_google_exception
from app.schemas.image import ProviderImageGenerateWithReferenceRequest, ProviderImageRequest, ImageResponse
from app.services.image.mock_assets import MOCK_PNG
from app.services.image.references import build_edit_prompt, load_reference_image_bytes
from app.services.image.storage import store_image
from app.services.text.prompts import append_visual_safety_guardrails

DEPRECATED_IMAGEN_MODELS = {
    "imagen-4.0-generate-001",
    "imagen-4.0-ultra-generate-001",
    "imagen-4.0-fast-generate-001",
}

NANO_BANANA_MODELS = {
    "gemini-2.5-flash-image",
}

GLOBAL_VERTEX_MODELS: set[str] = set()

logger = logging.getLogger(__name__)


async def generate_google_images(request: ProviderImageRequest) -> ImageResponse:
    settings = get_settings()
    model = request.model or settings.google_default_image_model
    if not settings.is_live_ai_enabled:
        urls = [await store_image(MOCK_PNG, extension=request.output_format) for _ in range(request.n)]
        return ImageResponse(images=urls, model_used=f"mock:{model}", provider="google")

    if not settings.google_api_key:
        raise ProviderAuthenticationError("Google provider authentication failed.")

    try:
        if model in NANO_BANANA_MODELS:
            urls = await asyncio.to_thread(_generate_nano_banana_images_sync, request, settings, model)
        else:
            raise ProviderRequestError("Google provider rejected the request.")
    except ProviderError:
        raise
    except Exception as exc:
        logger.exception("Google image generation failed for model=%s", model)
        raise classify_google_exception(exc) from exc

    return ImageResponse(images=urls, model_used=model, provider="google")


async def edit_google_images(request: ProviderImageGenerateWithReferenceRequest) -> ImageResponse:
    settings = get_settings()
    model = request.model or settings.google_default_image_model
    if not settings.is_live_ai_enabled:
        urls = [await store_image(MOCK_PNG, extension=request.output_format) for _ in range(request.n)]
        return ImageResponse(images=urls, model_used=f"mock:{model}", provider="google")

    if model not in NANO_BANANA_MODELS:
        raise ProviderRequestError("Google provider rejected the request.")

    try:
        urls = await asyncio.to_thread(_edit_nano_banana_images_sync, request, settings, model)
    except ProviderError:
        raise
    except Exception as exc:
        logger.exception("Google image edit failed for model=%s", model)
        raise classify_google_exception(exc) from exc

    return ImageResponse(images=urls, model_used=model, provider="google")


def _generate_nano_banana_images_sync(request: ProviderImageRequest, settings, model: str) -> list[str]:
    from google.genai import types

    client = _build_google_client(settings, model)
    urls: list[str] = []

    for _ in range(request.n):
        response = client.models.generate_content(
            model=model,
            contents=append_visual_safety_guardrails(request.prompt),
            config=types.GenerateContentConfig(
                response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
            ),
        )
        image_bytes = _extract_first_image_bytes(response)
        urls.append(_store_image_sync_bridge(image_bytes, request.output_format))

    return urls


def _edit_nano_banana_images_sync(request: ProviderImageGenerateWithReferenceRequest, settings, model: str) -> list[str]:
    from google.genai import types

    client = _build_google_client(settings, model)
    contents = [append_visual_safety_guardrails(build_edit_prompt(request.prompt, request.text_to_render))]
    for reference in request.reference_images:
        if reference.file_id:
            raise ProviderRequestError("Google provider rejected the request.")
        contents.append(
            types.Part.from_bytes(
                data=load_reference_image_bytes(reference),
                mime_type=reference.mime_type,
            )
        )

    urls: list[str] = []
    for _ in range(request.n):
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
            ),
        )
        image_bytes = _extract_first_image_bytes(response)
        urls.append(_store_image_sync_bridge(image_bytes, request.output_format))

    return urls


def _build_google_client(settings, model: str | None = None, location: str | None = None):
    from google import genai

    if settings.google_auth_mode == "vertex_ai":
        if not settings.has_google_service_account:
            raise ProviderAuthenticationError("Google provider authentication failed.")
        if not settings.gcp_project_id:
            raise ProviderAuthenticationError("Google provider authentication failed.")

        import json
        from google.oauth2 import service_account

        try:
            service_account_info = json.loads(settings.gcp_service_account_json)
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        except Exception as exc:
            raise ProviderAuthenticationError("Google provider authentication failed.") from exc

        return genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=location or _resolve_vertex_location(settings, model),
            credentials=credentials,
        )

    if not settings.google_api_key:
        raise ProviderAuthenticationError("Google provider authentication failed.")
    return genai.Client(api_key=settings.google_api_key)


def _resolve_vertex_location(settings, model: str | None) -> str:
    if model in GLOBAL_VERTEX_MODELS:
        return "global"
    if settings.gcp_image_location:
        return settings.gcp_image_location
    return settings.gcp_location


def build_google_video_client(settings, model: str | None = None):
    return _build_google_client(settings, model=model, location=settings.gcp_video_location)


def _extract_first_image_bytes(response) -> bytes:
    for part in getattr(response, "parts", []) or []:
        inline_data = getattr(part, "inline_data", None)
        if inline_data is not None and getattr(inline_data, "data", None):
            return inline_data.data

    candidates = getattr(response, "candidates", []) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline_data = getattr(part, "inline_data", None)
            if inline_data is not None and getattr(inline_data, "data", None):
                return inline_data.data

    raise ProviderError("Google response did not include image data")


def _store_image_sync_bridge(image_bytes: bytes, output_format: str) -> str:
    # google-genai is currently sync in this service path. Running the whole
    # provider call in a thread lets us safely bridge back to the async adapter.
    return asyncio.run(store_image(image_bytes, extension=output_format))
