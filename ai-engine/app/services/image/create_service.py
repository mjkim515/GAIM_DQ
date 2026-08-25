import logging

from app.core.exceptions import AIEngineError, ProviderError, RequestValidationError
from app.core.provider_errors import provider_warning_message
from app.schemas.image import (
    ImageCreateResponse,
    ImageCreateRouting,
    ProviderImageGenerateWithReferenceRequest,
    ImageModelCandidate,
    ProviderImageRequest,
    ImageRequest,
    image_request_to_reference_request,
)
from app.services.image.google_service import edit_google_images, generate_google_images
from app.services.image.model_router import build_image_routing_plan, validate_routed_request
from app.services.image.mock_assets import MOCK_PNG
from app.services.image.openai_service import edit_openai_images, generate_openai_images
from app.services.image.storage import store_image

logger = logging.getLogger(__name__)


async def create_image(request: ImageRequest) -> ImageCreateResponse:
    routed_requests, candidates, primary_channel, final_prompt = build_image_routing_plan(request)
    warnings: list[str] = []
    attempted: list[ImageModelCandidate] = []
    routed_by_rank = {candidate.rank: routed for candidate, routed in zip(_provider_candidates(candidates), routed_requests)}

    for candidate in candidates:
        attempted.append(candidate)
        if candidate.provider == "local":
            return await _placeholder_response(candidate, attempted, primary_channel, final_prompt, warnings)

        routed_request = routed_by_rank[candidate.rank]
        try:
            validate_routed_request(routed_request)
            response = await _execute_candidate(candidate, routed_request)
            if candidate.rank != 1 and request.text_to_render:
                warnings.append(
                    "OpenAI text rendering failed; fell back to Google Nano Banana, Korean text accuracy may be lower."
                )
            return ImageCreateResponse(
                images=response.images,
                model_used=response.model_used,
                provider=response.provider,
                routing=ImageCreateRouting(
                    primary_channel=primary_channel,
                    final_prompt=final_prompt,
                    selected_rank=candidate.rank,
                    selected=candidate,
                    attempted_models=attempted,
                    fallback_used=candidate.rank != 1,
                    warnings=warnings,
                ),
            )
        except RequestValidationError:
            raise
        except (ProviderError, AIEngineError) as exc:
            logger.warning(
                "Image provider candidate failed rank=%s provider=%s model=%s: %s",
                candidate.rank,
                candidate.provider,
                candidate.model,
                exc,
            )
            warnings.append(
                f"Rank {candidate.rank} {candidate.provider}/{candidate.model} failed: {provider_warning_message(exc)}"
            )
        except Exception as exc:
            logger.exception(
                "Unexpected image provider candidate failure rank=%s provider=%s model=%s",
                candidate.rank,
                candidate.provider,
                candidate.model,
            )
            warnings.append(
                f"Rank {candidate.rank} {candidate.provider}/{candidate.model} failed: {provider_warning_message(exc)}"
            )

    return await _placeholder_response(candidates[-1], attempted, primary_channel, final_prompt, warnings)


async def _execute_candidate(candidate: ImageModelCandidate, request: ProviderImageRequest):
    if candidate.operation == "edit":
        edit_request = image_request_to_reference_request(request)
        return await _execute_edit(candidate, edit_request)
    if candidate.provider == "google":
        return await generate_google_images(request)
    if candidate.provider == "openai":
        return await generate_openai_images(request)
    raise ProviderError(f"Unsupported image candidate provider: {candidate.provider}")


async def _execute_edit(candidate: ImageModelCandidate, request: ProviderImageGenerateWithReferenceRequest):
    if candidate.provider == "google":
        return await edit_google_images(request)
    if candidate.provider == "openai":
        return await edit_openai_images(request)
    raise ProviderError(f"Unsupported image edit candidate provider: {candidate.provider}")


async def _placeholder_response(
    candidate: ImageModelCandidate,
    attempted: list[ImageModelCandidate],
    primary_channel: str,
    final_prompt: str,
    warnings: list[str],
) -> ImageCreateResponse:
    urls = [await store_image(MOCK_PNG, extension="png") for _ in range(candidate.n)]
    return ImageCreateResponse(
        images=urls,
        model_used=candidate.model,
        provider="local",
        routing=ImageCreateRouting(
            primary_channel=primary_channel,
            final_prompt=final_prompt,
            selected_rank=candidate.rank,
            selected=candidate,
            attempted_models=attempted,
            fallback_used=True,
            warnings=warnings + ["Provider generation failed or was unavailable; returned a local default placeholder image."],
        ),
    )


def _provider_candidates(candidates: list[ImageModelCandidate]) -> list[ImageModelCandidate]:
    return [candidate for candidate in candidates if candidate.provider != "local"]
