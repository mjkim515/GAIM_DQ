from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.core.security import verify_internal_token
from app.schemas.video import (
    VideoJobResponse,
    VideoRequest,
    VideoShortCreateRequest,
    VideoStatusResponse,
)
from app.services.video.veo_service import (
    enqueue_video_generation,
    enqueue_video_short_generation,
    get_video_status,
)

router = APIRouter(dependencies=[Depends(verify_internal_token)])

# Requests are idempotent by jobId within the running API process. Use distinct
# example IDs when a new generation run is intended.
VIDEO_SHORT_REQUEST_EXAMPLES = {
    "textToVideo": {
        "summary": "Text to video short",
        "value": {
            "jobId": "86fa94ee-2aa1-48e2-80bd-574dc8b0c7f3",
            "prompt": "벚꽃이 만발한 호숫가 근처를 골드리트리버와 함께 한 남자가 걷고 있어",
            "model": "fast",
            "platform": "youtube_shorts",
            "task": "textToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 4,
            "advanced": {
                "generateAudio": True,
            },
            "metadata": {
                "campaignId": "campaign-1",
            },
        },
    },
    "imageToVideo": {
        "summary": "Image to video short",
        "value": {
            "jobId": "29bfe3e3-f4f6-47b5-95c6-45e63ed1043f",
            "prompt": "이 이미지를 시작 프레임으로 자연스럽게 움직이는 숏폼 광고 생성",
            "model": "fast",
            "platform": "instagram_reels",
            "task": "imageToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 8,
            "input": {
                "image": {
                    "gcsUri": "gs://gaim-generated-assets/video-shorts/start-frame.png",
                    "mimeType": "image/png",
                }
            },
        },
    },
    "referenceToVideo": {
        "summary": "Reference images to video short",
        "value": {
            "jobId": "0d8a44ed-ae4c-4b47-ac24-c2815f68fb6b",
            "prompt": "레퍼런스 이미지를 참고해서 제품 중심 숏폼 광고 생성",
            "model": "standard",
            "platform": "tiktok",
            "task": "referenceToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 8,
            "input": {
                "referenceImages": [
                    {
                        "gcsUri": "gs://gaim-generated-assets/video-shorts/reference-1.png",
                        "mimeType": "image/png",
                    }
                ]
            },
        },
    },
    "runwayTextToVideo": {
        "summary": "Runway direct test - text to video",
        "value": {
            "jobId": "runway-text-test-1",
            "prompt": "따뜻한 조명의 동네 카페에서 시그니처 라떼가 테이블 위에 놓이고 카메라가 천천히 다가가는 숏폼 광고",
            "model": "fast",
            "providerOverride": "runway",
            "platform": "instagram_reels",
            "task": "textToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 4,
            "advanced": {
                "generateAudio": False,
            },
            "metadata": {
                "source": "ai-engine-swagger-runway-test",
            },
        },
    },
    "runwayImageToVideo": {
        "summary": "Runway direct test - image to video",
        "value": {
            "jobId": "runway-image-test-1",
            "prompt": "첫 프레임의 제품 구도는 유지하고, 따뜻한 자연광과 부드러운 카메라 푸시인으로 짧은 광고 영상 생성",
            "model": "standard",
            "providerOverride": "runway",
            "platform": "instagram_reels",
            "task": "imageToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 4,
            "input": {
                "image": {
                    "gcsUri": "https://example.com/product-start-frame.png",
                    "mimeType": "image/png",
                }
            },
            "advanced": {
                "generateAudio": False,
            },
            "metadata": {
                "source": "ai-engine-swagger-runway-test",
            },
        },
    },
}


@router.post(
    "/jobs",
    response_model=VideoJobResponse,
    summary="활성 영상 생성 Job API",
    description=(
        "운영 연동용 영상 생성 진입점입니다. WAS가 발급한 jobId를 포함해 요청하면 영상 생성 job을 등록하고 "
        "즉시 queued 응답을 반환합니다. 완료/실패/진행률은 WAS callback으로 전달되며, frontend는 WAS의 "
        "/api/ai/video/async/job/{jobId} 상태 API를 polling합니다."
    ),
)
async def generate_video_job_endpoint(
    request: Annotated[VideoShortCreateRequest, Body(openapi_examples=VIDEO_SHORT_REQUEST_EXAMPLES)],
) -> VideoJobResponse:
    return await enqueue_video_short_generation(request)


# Deprecated route kept as source reference only. Do not register it; WAS should call POST /v1/video/jobs.
# @router.post("/short", response_model=VideoJobResponse)
# async def generate_video_short_endpoint(
#     request: Annotated[VideoShortCreateRequest, Body(openapi_examples=VIDEO_SHORT_REQUEST_EXAMPLES)],
# ) -> VideoJobResponse:
#     return await enqueue_video_short_generation(request)


@router.get(
    "/status/{job_id}",
    response_model=VideoStatusResponse,
    summary="[개발/레거시] ai-engine 내부 영상 Job 상태 조회",
    description=(
        "개발 및 레거시 확인용 상태 API입니다. 운영 상태의 source of truth는 WAS이며, frontend는 "
        "/api/ai/video/async/job/{jobId}를 호출해야 합니다."
    ),
    deprecated=True,
)
async def get_video_status_endpoint(job_id: str) -> VideoStatusResponse:
    return await get_video_status(job_id)


@router.post(
    "/provider-generate",
    response_model=VideoJobResponse,
    summary="[테스트용/비운영] Provider 직접 영상 생성 API",
    description=(
        "Google Veo provider 모델명을 직접 지정해 동작을 확인하는 테스트 API입니다. 운영 연동은 이 경로가 아니라 "
        "POST /v1/video/jobs를 사용합니다."
    ),
)
async def provider_generate_video_endpoint(request: VideoRequest) -> VideoJobResponse:
    return await enqueue_video_generation(request)
