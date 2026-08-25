from fastapi import APIRouter, Depends

from app.core.security import verify_internal_token
from app.schemas.text import BrandTextRequest, MarketingTextRequest, RefineTextRequest, TextRequest, TextResponse
from app.services.text.openai_service import (
    generate_brand_text,
    generate_marketing_text,
    generate_refine_text,
    generate_text,
)

router = APIRouter(dependencies=[Depends(verify_internal_token)])



@router.post("/brand", response_model=TextResponse, summary="profile_summary | brand_ad_copy | brand_image_prompt 모드, 브랜드 프로필 기반 텍스트 생성")
async def generate_brand_text_endpoint(request: BrandTextRequest) -> TextResponse:
    return await generate_brand_text(request)


@router.post(
    "/marketing",
    response_model=TextResponse,
    summary="product_detail | ad_copy | sns_post | customer_message 모드, 마케팅 텍스트 생성",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "product_detail": {
                            "summary": "상품 상세 설명 - 감자빵 상세페이지",
                            "value": {
                                "content_type": "product_detail",
                                "input": {
                                    "topic": "강원도 수제 감자빵",
                                    "purpose": "instagram_promotion",
                                    "tone": "emotional",
                                    "target_audience": "20~30대 여성",
                                    "highlight_points": ["촉촉한 식감", "국내산 감자"],
                                },
                                "options": {
                                    "length": "short",
                                    "number_of_variations": 3,
                                    "must_include": [],
                                    "must_avoid": [],
                                    "allow_hashtags": False,
                                    "allow_emoji": False,
                                    "max_tokens": 500,
                                },
                            },
                        },
                        "ad_copy": {
                            "summary": "광고 문구 / 카피 - 클릭 유도",
                            "value": {
                                "content_type": "ad_copy",
                                "input": {
                                    "topic": "춘천 감자빵 선물세트",
                                    "purpose": "ad_click",
                                    "tone": "premium",
                                    "target_audience": "강원도 여행 기념품을 찾는 고객",
                                    "highlight_points": ["개별 포장", "선물용 추천"],
                                },
                                "options": {
                                    "length": "short",
                                    "number_of_variations": 4,
                                    "must_include": ["선물세트"],
                                    "must_avoid": ["전국 1등"],
                                    "allow_hashtags": False,
                                    "allow_emoji": False,
                                    "max_tokens": 500,
                                },
                            },
                        },
                        "sns_post": {
                            "summary": "SNS 게시글 - 인스타 홍보",
                            "value": {
                                "content_type": "sns_post",
                                "input": {
                                    "topic": "강원도 수제 감자빵",
                                    "purpose": "instagram_promotion",
                                    "tone": "lively",
                                    "target_audience": "춘천 여행 중인 20~30대",
                                    "highlight_points": ["갓 구운 빵", "카페에서 바로 픽업"],
                                },
                                "options": {
                                    "length": "medium",
                                    "number_of_variations": 2,
                                    "must_include": ["춘천"],
                                    "must_avoid": ["과장된 할인 표현"],
                                    "allow_hashtags": True,
                                    "allow_emoji": True,
                                    "max_tokens": 700,
                                },
                            },
                        },
                        "customer_message": {
                            "summary": "고객 응답 / 메시지 - 문의 답변",
                            "value": {
                                "content_type": "customer_message",
                                "input": {
                                    "topic": "감자빵 택배 가능 여부 문의",
                                    "purpose": "customer_response",
                                    "tone": "professional",
                                    "target_audience": "온라인 문의 고객",
                                    "highlight_points": ["정확한 안내", "친절한 답변"],
                                },
                                "options": {
                                    "length": "short",
                                    "number_of_variations": 2,
                                    "must_include": ["확인 후 안내"],
                                    "must_avoid": ["확정되지 않은 배송 약속"],
                                    "allow_hashtags": False,
                                    "allow_emoji": False,
                                    "max_tokens": 500,
                                },
                            },
                        },
                    }
                }
            }
        }
    },
)
async def generate_marketing_text_endpoint(request: MarketingTextRequest) -> TextResponse:
    return await generate_marketing_text(request)


@router.post(
    "/refine",
    response_model=TextResponse,
    summary="content_prompt_rewrite | copy_rewrite 모드, 기존 입력 문구 개선",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "image_prompt_rewrite": {
                            "summary": "이미지 프롬프트 재작성 - 선택 무드/비율 반영",
                            "value": {
                                "model": "auto",
                                "mode": "content_prompt_rewrite",
                                "language": "ko",
                                "brand": {
                                    "name": "강릉 커피집",
                                    "category": "카페",
                                    "location": "강릉 교동",
                                    "description": "로컬 원두와 수제 디저트를 판매하는 동네 카페",
                                },
                                "input": {
                                    "text": "카페에서 라떼 사진",
                                },
                                "target": {
                                    "channel": "instagram_story",
                                    "tone": "감성적",
                                    "format": "image_prompt",
                                    "visualMood": "warm_cozy",
                                    "aspectRatio": "9:16",
                                },
                            },
                        },
                        "shortform_video_prompt_rewrite": {
                            "summary": "숏폼 영상 프롬프트 재작성 - 플랫폼/비율/길이 반영",
                            "value": {
                                "model": "auto",
                                "mode": "content_prompt_rewrite",
                                "language": "ko",
                                "brand": {
                                    "name": "G-AIM",
                                    "category": "AI 마케팅",
                                    "brand_voice": "실용적이고 선명한",
                                    "target_audience": "로컬 비즈니스 마케터",
                                },
                                "input": {
                                    "text": "신메뉴 출시를 알리는 짧은 영상",
                                },
                                "target": {
                                    "channel": "instagram_reels",
                                    "platform": "instagram_reels",
                                    "tone": "commercial",
                                    "format": "shortform_video_prompt",
                                    "aspectRatio": "9:16",
                                    "durationSeconds": 8,
                                },
                            },
                        },
                    }
                }
            }
        }
    },
)
async def generate_refine_text_endpoint(request: RefineTextRequest) -> TextResponse:
    return await generate_refine_text(request)

@router.post("/generate", response_model=TextResponse, summary="[테스트용] - Prompt 직접 입력 범용 텍스트 생성 API")
async def generate_text_endpoint(request: TextRequest) -> TextResponse:
    return await generate_text(request)
