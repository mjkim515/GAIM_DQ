from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Query

from app.config import get_settings
from app.core.exceptions import AIEngineError, ProviderError, RequestValidationError
from app.core.provider_errors import provider_warning_message
from app.core.security import verify_internal_token
from app.schemas.image import (
    ProviderImageGenerateWithReferenceRequest,
    ImageIntentRequest,
    ImageIntentResponse,
    ImageJobRequest,
    ImageJobResponse,
    ImageModelInfo,
    ProviderImageRequest,
    ImageResponse,
    image_request_to_reference_request,
)
from app.services.image.google_service import edit_google_images, generate_google_images
from app.services.image.model_router import (
    apply_text_free_provider_policy,
    apply_text_free_reference_provider_policy,
    build_intent_routing_decision,
    build_intent_routing_plan,
    openai_default_edit_model,
    openai_default_generate_model,
    validate_routed_request,
)
from app.services.image.mock_assets import MOCK_PNG
from app.services.image.openai_service import OPENAI_IMAGE_MODELS, edit_openai_images, generate_openai_images
from app.services.image.storage import store_image
from app.workers.tasks.image_tasks import generate_image_task

router = APIRouter(dependencies=[Depends(verify_internal_token)])

# Requests are idempotent by jobId within the running API process. Use distinct
# example IDs when a new generation run is intended.
_IMAGE_JOB_IDS: set[str] = set()

IMAGE_JOB_REQUEST_EXAMPLES = {
    "promotion_sns": {
        "summary": "홍보 SNS 이미지 Job",
        "value": {
            "jobId": "15f5c63c-dfd2-4a06-a8b7-1681e1b45f61",
            "purpose": "홍보",
            "channels": ["instagram"],
            "image_prompt": "따뜻한 조명의 매장에서 대표 메뉴가 테이블 위에 정갈하게 놓인 모습",
            "visual_mood": "warm_cozy",
            "n": 1,
        },
    },
    "text_insert": {
        "summary": "텍스트 삽입 이미지 Job",
        "value": {
            "jobId": "7cc3cf78-8975-4e7e-9001-19368a0eccc1",
            "purpose": "이벤트",
            "channels": ["instagram_story"],
            "image_prompt": "봄맞이 이벤트 광고 이미지",
            "text_to_render": "오늘 딸기 30% 할인",
            "text_rendering": {
                "text": "오늘 딸기 30% 할인",
                "language": "ko",
                "placement": "bottom",
                "must_render_exactly": True,
            },
            "visual_mood": "bright",
            "n": 1,
        },
    },
}

# Deprecated sync route kept as source reference only. Do not register:
# POST /v1/image/generate
#
# @router.post(
#     "/generate",
#     response_model=ImageCreateResponse,
#     summary="이미지 생성 API",
#     description=(
#         "마케팅 이미지 생성의 기본 진입점입니다. 텍스트 렌더링 요청이 있으면 내부적으로 텍스트 정확도 우선 "
#         "정책을 적용해 OpenAI GPT Image를 먼저 사용하고, 실패 시 Google Nano Banana로 fallback합니다."
#     ),
#     openapi_extra={
#         "requestBody": {
#             "content": {
#                 "application/json": {
#                     "examples": {
#                         "promotion_sns": {
#                             "summary": "홍보 SNS 이미지",
#                             "value": {
#                                 "purpose": "홍보",
#                                 "channels": ["인스타", "SNS"],
#                                 "image_prompt": "나무가 울창한 호숫가에 위치한 카페 이미지를 만들어줘",
#                                 "visual_mood": "warm_cozy",
#                                 "n": 3,
#                             },
#                         },
#                         "brand_banner": {
#                             "summary": "브랜드 배너 이미지",
#                             "value": {
#                                 "purpose": "브랜드",
#                                 "channels": ["배너", "블로그"],
#                                 "image_prompt": "프리미엄 과일 선물세트를 소개하는 고급스러운 브랜드 이미지",
#                                 "visual_mood": "premium",
#                                 "n": 1,
#                             },
#                         },
#                         "reference_image": {
#                             "summary": "참조 이미지 기반 생성 - 텍스트 없음",
#                             "value": {
#                                 "purpose": "이벤트",
#                                 "channels": ["인스타"],
#                                 "image_prompt": "참조 이미지를 활용해서 과일 가게 봄맞이 이벤트 이미지로 만들어줘",
#                                 "reference_images": [
#                                     {
#                                         "image_url": "http://localhost:8000/generated/images/source.png",
#                                         "mime_type": "image/png",
#                                     }
#                                 ],
#                                 "visual_mood": "bright",
#                                 "n": 1,
#                             },
#                         },
#                         "text_insert_without_reference": {
#                             "summary": "텍스트 삽입 이미지 생성 - OpenAI 우선",
#                             "value": {
#                                 "purpose": "홍보",
#                                 "channels": ["인스타"],
#                                 "image_prompt": "과일 가게 할인 행사 홍보 이미지",
#                                 "text_rendering": {
#                                     "text": "오늘 딸기 30% 할인",
#                                     "language": "ko",
#                                     "placement": "bottom",
#                                     "must_render_exactly": True,
#                                 },
#                                 "visual_mood": "vibrant",
#                                 "n": 1,
#                             },
#                         },
#                         "text_insert_with_reference": {
#                             "summary": "참조 이미지 기반 텍스트 삽입 - OpenAI 우선",
#                             "value": {
#                                 "purpose": "이벤트",
#                                 "channels": ["인스타"],
#                                 "image_prompt": "참조 이미지를 기반으로 봄맞이 이벤트 광고 이미지로 편집하고 문구를 넣어줘",
#                                 "reference_images": [
#                                     {
#                                         "image_url": "http://localhost:8000/generated/images/source.png",
#                                         "mime_type": "image/png",
#                                     }
#                                 ],
#                                 "text_to_render": "오늘의 신선 과일",
#                                 "visual_mood": "bright",
#                                 "n": 1,
#                             },
#                         },
#                     }
#                 }
#             }
#         }
#     },
# )
# async def create_image_endpoint(request: ImageRequest) -> ImageCreateResponse:
#     return await create_image(request)


@router.post(
    "/jobs",
    response_model=ImageJobResponse,
    summary="활성 이미지 생성 Job API",
    description=(
        "운영 연동용 이미지 생성 진입점입니다. WAS가 발급한 jobId를 포함해 요청하면 Celery queue에 등록하고 "
        "즉시 queued 응답을 반환합니다. 완료/실패/진행률은 WAS callback으로 전달되며, frontend는 WAS의 "
        "/api/ai/image/async/job/{jobId} 상태 API를 polling합니다."
    ),
)
async def enqueue_image_job_endpoint(
    request: Annotated[ImageJobRequest, Body(openapi_examples=IMAGE_JOB_REQUEST_EXAMPLES)],
) -> ImageJobResponse:
    if request.job_id in _IMAGE_JOB_IDS:
        return ImageJobResponse(
            jobId=request.job_id,
            status="queued",
            message="이미 등록된 jobId입니다. 기존 이미지 생성 작업을 반환합니다.",
        )

    _IMAGE_JOB_IDS.add(request.job_id)
    try:
        generate_image_task.apply_async(args=[request.model_dump(by_alias=True)], queue="image-queue")
    except Exception:
        _IMAGE_JOB_IDS.discard(request.job_id)
        raise
    return ImageJobResponse(
        jobId=request.job_id,
        status="queued",
        message="이미지 생성 작업이 큐에 등록되었습니다.",
    )


@router.post(
    "/provider-generate",
    response_model=ImageResponse,
    summary="[테스트용/비운영] Provider 직접 이미지 생성 API",
    description=(
        "Provider 라우팅과 모델 응답을 직접 확인하기 위한 동기 테스트 API입니다. 운영 연동은 이 경로가 아니라 "
        "POST /v1/image/jobs를 사용합니다."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "openai_gpt_image": {
                            "summary": "OpenAI GPT Image 2 - 텍스트 삽입",
                            "value": {
                                "provider": "openai",
                                "model": "gpt-image-2",
                                "prompt": "과일 가게 할인 행사 홍보 이미지를 만들고, 이미지 하단에 문구를 선명하게 넣어줘",
                                "text_to_render": "오늘 딸기 30% 할인",
                                "size": "1024x1024",
                                "quality": "low",
                                "output_format": "png",
                                "background": "auto",
                                "style": "vivid",
                                "n": 1,
                            },
                        },
                        "google_nano_banana": {
                            "summary": "Google Nano Banana",
                            "value": {
                                "provider": "google",
                                "model": "gemini-2.5-flash-image",
                                "prompt": "나무가 울창한 호숫가에 위치한 카페 이미지를 만들어줘",
                                "size": "auto",
                                "quality": "auto",
                                "output_format": "png",
                                "background": "auto",
                                "style": "vivid",
                                "n": 1,
                            },
                        },
                        "google_nano_banana_with_reference": {
                            "summary": "Google Nano Banana with reference image",
                            "value": {
                                "provider": "google",
                                "model": "gemini-2.5-flash-image",
                                "prompt": "참조 이미지를 기반으로 광고 이미지를 만들어줘",
                                "reference_images": [
                                    {
                                        "image_url": "http://localhost:8000/generated/images/source.png",
                                        "mime_type": "image/png",
                                    }
                                ],
                                "text_to_render": "오늘의 신선 과일",
                                "size": "auto",
                                "quality": "auto",
                                "output_format": "png",
                                "background": "auto",
                                "style": "vivid",
                                "n": 1,
                            },
                        },
                    }
                }
            }
        }
    },
)
async def generate_image_endpoint(request: ProviderImageRequest) -> ImageResponse:
    if request.provider == "openai" and not request.model:
        default_model = openai_default_edit_model() if request.reference_images else openai_default_generate_model()
        request = request.model_copy(update={"model": default_model})
    request = apply_text_free_provider_policy(request)
    validate_routed_request(request)
    if request.reference_images:
        edit_request = image_request_to_reference_request(request)
        if request.provider == "google":
            return await edit_google_images(edit_request)
        return await edit_openai_images(edit_request)
    if request.provider == "google":
        return await generate_google_images(request)
    return await generate_openai_images(request)


@router.post(
    "/provider-generate-with-reference",
    response_model=ImageResponse,
    summary="[테스트용/비운영] Provider 직접 참조 이미지 생성 API",
    description=(
        "참조 이미지 기반 provider 동작을 직접 확인하기 위한 동기 테스트 API입니다. 운영 연동은 이 경로가 아니라 "
        "POST /v1/image/jobs를 사용합니다."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "openai_generate_with_reference": {
                            "summary": "OpenAI generate with reference image",
                            "value": {
                                "provider": "openai",
                                "model": "gpt-image-2",
                                "prompt": "참조 이미지를 기반으로 광고 이미지를 만들어줘",
                                "reference_images": [
                                    {
                                        "image_url": "http://localhost:8000/generated/images/source.png",
                                        "mime_type": "image/png",
                                    }
                                ],
                                "text_to_render": "오늘의 신선 과일",
                                "size": "1024x1024",
                                "quality": "low",
                                "output_format": "png",
                                "background": "auto",
                                "input_fidelity": "high",
                                "n": 1,
                            },
                        },
                        "google_nano_banana_generate_with_reference": {
                            "summary": "Google Nano Banana generate with reference image",
                            "value": {
                                "provider": "google",
                                "model": "gemini-2.5-flash-image",
                                "prompt": "참조 이미지를 기반으로 광고 이미지를 만들어줘",
                                "reference_images": [
                                    {
                                        "image_url": "http://localhost:8000/generated/images/source.png",
                                        "mime_type": "image/png",
                                    }
                                ],
                                "text_to_render": "오늘의 신선 과일",
                                "size": "auto",
                                "quality": "auto",
                                "output_format": "png",
                                "background": "auto",
                                "input_fidelity": "high",
                                "n": 1,
                            },
                        },
                    }
                }
            }
        }
    },
)
async def generate_image_with_reference_endpoint(request: ProviderImageGenerateWithReferenceRequest) -> ImageResponse:
    if request.provider == "openai" and not request.model:
        request = request.model_copy(update={"model": openai_default_edit_model()})
    request = apply_text_free_reference_provider_policy(request)
    validate_routed_request(
        ProviderImageRequest(
            provider=request.provider,
            model=request.model,
            prompt=request.prompt,
            reference_images=request.reference_images,
            text_to_render=request.text_to_render,
            size=request.size,
            quality=request.quality,
            output_format=request.output_format,
            background=request.background,
            n=request.n,
        )
    )
    if request.provider == "google":
        return await edit_google_images(request)
    return await edit_openai_images(request)


@router.post(
    "/intent",
    response_model=ImageIntentResponse,
    summary="[테스트용] - Intent 기반 이미지 생성 API",
    description=(
        "Deprecated: 신규 연동은 /v1/image/jobs를 사용하세요. 이 엔드포인트는 기존 intent 기반 테스트 호환을 위해 유지됩니다."
    ),
    deprecated=True,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "image_sns_draft": {
                            "summary": "소상공인 SNS 시안 생성",
                            "value": {
                                "task": "generate",
                                "purpose": "draft",
                                "channel": "instagram_feed",
                                "quality_priority": "cost",
                                "text_importance": "low",
                                "prompt": "나무가 울창한 호숫가에 위치한 카페 이미지를 만들어줘",
                                "n": 3,
                            },
                        },
                        "text_insert_without_reference": {
                            "summary": "텍스트 삽입 이미지 생성 - OpenAI 우선",
                            "value": {
                                "task": "text_insert",
                                "purpose": "sns_post",
                                "channel": "instagram_feed",
                                "quality_priority": "text_accuracy",
                                "text_importance": "high",
                                "prompt": "과일 가게 할인 행사 홍보 이미지",
                                "text_rendering": {
                                    "text": "오늘 딸기 30% 할인",
                                    "language": "ko",
                                    "placement": "bottom",
                                    "must_render_exactly": True,
                                },
                                "n": 1,
                            },
                        },
                        "text_insert_with_reference": {
                            "summary": "참조 이미지 기반 텍스트 삽입 - OpenAI 우선",
                            "value": {
                                "task": "text_insert",
                                "purpose": "sns_post",
                                "channel": "instagram_story",
                                "quality_priority": "text_accuracy",
                                "text_importance": "high",
                                "prompt": "참조 이미지를 기반으로 인스타그램 스토리 광고로 편집하고 문구를 넣어줘",
                                "reference_images": [
                                    {
                                        "image_url": "http://localhost:8000/generated/images/source.png",
                                        "mime_type": "image/png",
                                    }
                                ],
                                "text_to_render": "오늘의 신선 과일",
                                "n": 1,
                            },
                        },
                        "reference_edit_without_text": {
                            "summary": "참조 이미지 편집 - 텍스트 없음",
                            "value": {
                                "task": "edit",
                                "purpose": "sns_post",
                                "channel": "instagram_story",
                                "quality_priority": "cost",
                                "text_importance": "none",
                                "prompt": "참조 이미지를 기반으로 인스타그램 스토리 광고로 편집해줘",
                                "reference_images": [
                                    {
                                        "image_url": "http://localhost:8000/generated/images/source.png",
                                        "mime_type": "image/png",
                                    }
                                ],
                                "n": 1,
                            },
                        },
                    }
                }
            }
        }
    },
)
async def create_image_from_intent_endpoint(request: ImageIntentRequest) -> ImageIntentResponse:
    routed_requests, candidates = build_intent_routing_plan(request)
    warnings: list[str] = []
    attempted = []
    routed_by_rank = {
        candidate.rank: routed
        for candidate, routed in zip((candidate for candidate in candidates if candidate.provider != "local"), routed_requests)
    }

    for candidate in candidates:
        attempted.append(candidate)
        if candidate.provider == "local":
            urls = [await store_image(MOCK_PNG, extension="png") for _ in range(candidate.n)]
            return ImageIntentResponse(
                images=urls,
                model_used=candidate.model,
                provider="local",
                routing=build_intent_routing_decision(
                    candidate,
                    attempted,
                    warnings + ["Provider generation failed or was unavailable; returned a local default placeholder image."],
                ),
            )

        routed_request = routed_by_rank[candidate.rank]
        try:
            validate_routed_request(routed_request)
            if candidate.operation == "edit":
                edit_request = image_request_to_reference_request(routed_request)
                if routed_request.provider == "google":
                    response = await edit_google_images(edit_request)
                else:
                    response = await edit_openai_images(edit_request)
            elif routed_request.provider == "google":
                response = await generate_google_images(routed_request)
            else:
                response = await generate_openai_images(routed_request)

            if candidate.rank != 1 and _intent_request_has_text(request):
                warnings.append(
                    "OpenAI text rendering failed; fell back to Google Nano Banana, Korean text accuracy may be lower."
                )
            return ImageIntentResponse(
                images=response.images,
                model_used=response.model_used,
                provider=response.provider,
                routing=build_intent_routing_decision(candidate, attempted, warnings),
            )
        except RequestValidationError:
            raise
        except (ProviderError, AIEngineError) as exc:
            warnings.append(
                f"Rank {candidate.rank} {candidate.provider}/{candidate.model} failed: {provider_warning_message(exc)}"
            )
        except Exception as exc:
            warnings.append(
                f"Rank {candidate.rank} {candidate.provider}/{candidate.model} failed: {provider_warning_message(exc)}"
            )

    candidate = candidates[-1]
    urls = [await store_image(MOCK_PNG, extension="png") for _ in range(candidate.n)]
    return ImageIntentResponse(
        images=urls,
        model_used=candidate.model,
        provider="local",
        routing=build_intent_routing_decision(candidate, attempted, warnings),
    )


def _intent_request_has_text(request: ImageIntentRequest) -> bool:
    return bool(request.text_rendering or request.text_to_render)


@router.get("/models", summary="[테스트용] - Provider별 이미지 생성 모델 정보 API", response_model=ImageModelInfo)
async def get_image_models_endpoint(provider: Literal["openai", "google"] = Query(default="openai")) -> ImageModelInfo:
    settings = get_settings()
    if provider == "google":
        return ImageModelInfo(
            provider="google",
            default_model=settings.google_default_image_model,
            supported_models=settings.google_image_models,
            default_quality="auto",
            supported_sizes=["auto", "1:1", "3:4", "4:3", "9:16", "16:9", "1024x1024"],
            supported_qualities=["auto"],
            supported_output_formats=["png"],
        )

    return ImageModelInfo(
        provider="openai",
        default_model=settings.openai_default_image_model,
        supported_models=settings.openai_image_models or sorted(OPENAI_IMAGE_MODELS),
        default_quality=settings.openai_default_image_quality,
        supported_sizes=["1024x1024", "1536x1024", "1024x1536", "auto"],
        supported_qualities=["low", "medium", "high", "auto"],
        supported_output_formats=["png", "jpeg", "webp"],
    )
