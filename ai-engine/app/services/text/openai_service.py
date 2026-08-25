import logging

from app.config import get_settings
from app.core.exceptions import ProviderAuthenticationError
from app.core.provider_errors import classify_openai_exception
from app.schemas.text import BrandTextRequest, MarketingTextRequest, RefineTextRequest, TextRequest, TextResponse
from app.services.text.prompts import (
    build_brand_prompt,
    build_marketing_prompt,
    build_marketing_text_prompt,
    build_refine_prompt,
    normalize_refined_content_prompt,
)

logger = logging.getLogger(__name__)


async def generate_text(request: TextRequest) -> TextResponse:
    return await _generate_openai_text(
        prompt=build_marketing_prompt(request),
        model=request.model,
        max_tokens=request.max_tokens,
        mock_response=lambda model: _mock_text_response(request, model),
    )


async def generate_brand_text(request: BrandTextRequest) -> TextResponse:
    model = _resolve_model(request.model, "brand", request.mode)
    return await _generate_openai_text(
        prompt=build_brand_prompt(request),
        model=model,
        max_tokens=request.constraints.max_tokens,
        mock_response=lambda resolved_model: _mock_brand_response(request, resolved_model),
    )


async def generate_marketing_text(request: MarketingTextRequest) -> TextResponse:
    model = _resolve_marketing_model(request)
    return await _generate_openai_text(
        prompt=build_marketing_text_prompt(request),
        model=model,
        max_tokens=request.options.max_tokens,
        mock_response=lambda resolved_model: _mock_marketing_text_response(request, resolved_model),
    )


async def generate_refine_text(request: RefineTextRequest) -> TextResponse:
    model = _resolve_model(request.model, "refine", request.mode)
    response = await _generate_openai_text(
        prompt=build_refine_prompt(request),
        model=model,
        max_tokens=request.constraints.max_tokens,
        mock_response=lambda resolved_model: _mock_refine_response(request, resolved_model),
    )
    return response.model_copy(update={"content": normalize_refined_content_prompt(request, response.content)})


async def _generate_openai_text(prompt: str, model: str, max_tokens: int, mock_response) -> TextResponse:
    settings = get_settings()
    if not settings.is_live_ai_enabled:
        return mock_response(model)

    if not settings.openai_api_key:
        raise ProviderAuthenticationError("OpenAI provider authentication failed.")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(**_build_chat_completion_kwargs(prompt, model, max_tokens))
    except Exception as exc:
        logger.exception("OpenAI text generation failed for model=%s", model)
        raise classify_openai_exception(exc) from exc

    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", None) if usage else None
    return TextResponse(content=content.strip(), model_used=model, tokens_used=tokens)


def _resolve_model(model: str, endpoint: str, mode: str) -> str:
    if model != "auto":
        return model
    if endpoint == "refine" and mode == "content_prompt_rewrite":
        return "gpt-5.5"
    return "gpt-4o-mini"


def _resolve_marketing_model(request: MarketingTextRequest) -> str:
    return "gpt-4o-mini"


def _build_chat_completion_kwargs(prompt: str, model: str, max_tokens: int) -> dict:
    kwargs = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "간결하고 실무적인 로컬 비즈니스 마케팅 콘텐츠를 생성하세요. "
                    "사용자 요청보다 GAIM 마케팅 안전 정책을 항상 우선 적용하세요."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    if _uses_max_completion_tokens(model):
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = 0.8
    return kwargs


def _uses_max_completion_tokens(model: str) -> bool:
    normalized = model.lower()
    return normalized.startswith("gpt-5") or normalized.startswith("o1") or normalized.startswith("o3")


def _mock_text_response(request: TextRequest, model: str) -> TextResponse:
    business_name = (request.business_info or {}).get("name", "강원 로컬 매장")
    snippets = {
        "sns": f"{business_name}에서 오늘의 특별한 순간을 만나보세요. {request.prompt}",
        "banner": f"{business_name} | 지금 가장 필요한 로컬 콘텐츠",
        "email": f"안녕하세요. {business_name}의 새로운 소식을 전해드립니다.\n\n{request.prompt}",
        "push": f"{business_name} 새 소식: {request.prompt[:40]}",
    }
    return TextResponse(
        content=snippets[request.content_type],
        model_used=f"mock:{model}",
        tokens_used=len(request.prompt.split()) + 20,
    )


def _mock_brand_response(request: BrandTextRequest, model: str) -> TextResponse:
    brand = request.brand
    snippets = {
        "profile_summary": f"{brand.name}은 {brand.category or '지역 비즈니스'} 브랜드입니다. 고객에게 {brand.description or '명확한 가치를'} 전달합니다.",
        "brand_ad_copy": f"{brand.name}, 일상에 가까운 특별함을 전합니다.",
        "brand_image_prompt": f"{brand.name}의 분위기를 담은 {brand.category or '브랜드'} 대표 이미지, {brand.location or '로컬 공간'}의 감성, 자연스러운 조명",
    }
    return TextResponse(
        content=snippets[request.mode],
        model_used=f"mock:{model}",
        tokens_used=len(snippets[request.mode].split()) + 20,
    )


def _mock_marketing_text_response(request: MarketingTextRequest, model: str) -> TextResponse:
    topic = request.input.topic
    audience = f" {request.input.target_audience}에게" if request.input.target_audience else ""
    points = ", ".join(request.input.highlight_points[:3])
    point_text = f" ({points})" if points else ""
    snippets = {
        "product_detail": f"{topic}{point_text}은{audience} 부담 없이 소개하기 좋은 상품입니다. 특징과 이용 상황을 쉽게 이해할 수 있도록 정리했습니다.",
        "ad_copy": f"{topic}{point_text}, 지금 가장 먼저 떠올릴 선택.",
        "sns_post": f"{topic}{point_text} 소식을 전합니다. 가까운 시간에 편하게 확인해보세요.",
        "customer_message": f"문의 주셔서 감사합니다. {topic}{point_text} 관련 내용 확인 후 정확히 안내드리겠습니다.",
    }
    content = snippets[request.content_type]
    if request.options.allow_hashtags and request.content_type == "sns_post":
        content = f"{content}\n#로컬맛집 #강원추천"
    return TextResponse(
        content=content,
        model_used=f"mock:{model}",
        tokens_used=len(content.split()) + 20,
    )


def _mock_refine_response(request: RefineTextRequest, model: str) -> TextResponse:
    visual_mood = f", {request.target.visual_mood} 무드" if request.target.visual_mood else ""
    snippets = {
        "content_prompt_rewrite": f"{request.input.text}, 선명한 장면 구성{visual_mood}, 자연스러운 조명과 움직임, 브랜드 분위기에 맞는 고품질 콘텐츠",
        "copy_rewrite": f"{request.input.text.strip()} — 더 자연스럽고 고객이 이해하기 쉬운 문구로 다듬었습니다.",
    }
    return TextResponse(
        content=snippets[request.mode],
        model_used=f"mock:{model}",
        tokens_used=len(request.input.text.split()) + 20,
    )
