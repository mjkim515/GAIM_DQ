import base64
import logging
from io import BytesIO

from app.config import get_settings
from app.core.exceptions import ProviderAuthenticationError, ProviderError
from app.core.provider_errors import classify_openai_exception
from app.schemas.image import ProviderImageGenerateWithReferenceRequest, ProviderImageRequest, ImageResponse
from app.services.image.mock_assets import MOCK_PNG
from app.services.image.references import build_edit_prompt, load_reference_image_bytes
from app.services.image.storage import store_image
from app.services.text.prompts import append_visual_safety_guardrails

OPENAI_IMAGE_MODELS = {
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1",
    "gpt-image-1-mini",
}

OPENAI_IMAGE_QUALITY_MODELS = {
    "gpt-image-2",
    "gpt-image-1.5",
}

OPENAI_IMAGE_STANDARD_MODELS = {
    "gpt-image-1.5",
    "gpt-image-1",
}

OPENAI_IMAGE_FAST_MODELS = {
    "gpt-image-1-mini",
}

OPENAI_IMAGE_EDIT_MODELS = {
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1",
    "gpt-image-1-mini",
}

logger = logging.getLogger(__name__)


async def generate_openai_images(request: ProviderImageRequest) -> ImageResponse:
    settings = get_settings()
    model = request.model or settings.openai_standard_image_model
    quality = request.quality or settings.openai_default_image_quality
    if not settings.is_live_ai_enabled:
        urls = [await store_image(MOCK_PNG, extension=request.output_format) for _ in range(request.n)]
        return ImageResponse(images=urls, model_used=f"mock:{model}", provider="openai")

    if not settings.openai_api_key:
        raise ProviderAuthenticationError("OpenAI provider authentication failed.")

    client = None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_provider_timeout_sec)
        response = await client.images.generate(
            model=model,
            prompt=append_visual_safety_guardrails(request.prompt),
            size=request.size,
            quality=quality,
            output_format=request.output_format,
            background=request.background,
            n=request.n,
        )
    except Exception as exc:
        logger.exception("OpenAI image generation failed for model=%s", model)
        raise classify_openai_exception(exc) from exc
    finally:
        if client is not None:
            await client.close()

    urls: list[str] = []
    for item in response.data:
        if not item.b64_json:
            raise ProviderError("OpenAI image response did not include base64 data")
        urls.append(await store_image(base64.b64decode(item.b64_json), extension=request.output_format))
    return ImageResponse(images=urls, model_used=model, provider="openai")


async def edit_openai_images(request: ProviderImageGenerateWithReferenceRequest) -> ImageResponse:
    settings = get_settings()
    model = request.model or settings.openai_edit_image_model
    quality = request.quality or settings.openai_default_image_quality
    if not settings.is_live_ai_enabled:
        urls = [await store_image(MOCK_PNG, extension=request.output_format) for _ in range(request.n)]
        return ImageResponse(images=urls, model_used=f"mock:{model}", provider="openai")

    if not settings.openai_api_key:
        raise ProviderAuthenticationError("OpenAI provider authentication failed.")

    client = None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_provider_timeout_sec)
        image_inputs = []
        for index, reference in enumerate(request.reference_images):
            if reference.file_id:
                image_inputs.append(reference.file_id)
                continue
            image_bytes = load_reference_image_bytes(reference)
            file_name = f"reference-{index}.{_extension_from_mime_type(reference.mime_type)}"
            image_file = BytesIO(image_bytes)
            image_file.name = file_name
            image_inputs.append(image_file)

        response = await client.images.edit(
            **_build_openai_edit_kwargs(
                request=request,
                model=model,
                image_inputs=image_inputs,
                quality=quality,
            )
        )
    except Exception as exc:
        logger.exception("OpenAI image edit failed for model=%s", model)
        raise classify_openai_exception(exc) from exc
    finally:
        if client is not None:
            await client.close()

    urls: list[str] = []
    for item in response.data:
        if not item.b64_json:
            raise ProviderError("OpenAI image edit response did not include base64 data")
        urls.append(await store_image(base64.b64decode(item.b64_json), extension=request.output_format))
    return ImageResponse(images=urls, model_used=model, provider="openai")


def _extension_from_mime_type(mime_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/png": "png",
    }.get(mime_type, "png")


def _build_openai_edit_kwargs(
    request: ProviderImageGenerateWithReferenceRequest,
    model: str,
    image_inputs: list,
    quality: str,
) -> dict:
    kwargs = {
        "model": model,
        "image": image_inputs,
        "prompt": append_visual_safety_guardrails(build_edit_prompt(request.prompt, request.text_to_render)),
        "size": request.size,
        "quality": quality,
        "output_format": request.output_format,
        "background": request.background,
        "n": request.n,
    }
    if model != "gpt-image-2":
        kwargs["input_fidelity"] = request.input_fidelity
    return kwargs
