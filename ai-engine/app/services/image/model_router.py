from app.config import get_settings
from app.core.exceptions import RequestValidationError
from app.schemas.image import (
    ImageIntentRequest,
    ImageModelCandidate,
    ProviderImageGenerateWithReferenceRequest,
    ProviderImageRequest,
    ImageRoutingDecision,
    ImageRequest,
)
from app.services.image.google_service import DEPRECATED_IMAGEN_MODELS, NANO_BANANA_MODELS
from app.services.image.openai_service import (
    OPENAI_IMAGE_EDIT_MODELS,
    OPENAI_IMAGE_FAST_MODELS,
    OPENAI_IMAGE_MODELS,
    OPENAI_IMAGE_QUALITY_MODELS,
    OPENAI_IMAGE_STANDARD_MODELS,
)
from app.services.text.prompts import append_visual_safety_guardrails

EDIT_TASKS = {"edit", "inpaint", "outpaint", "background_replace", "style_transfer", "text_insert"}

CHANNEL_ASPECT_RATIOS = {
    "instagram_feed": "1:1",
    "instagram_story": "9:16",
    "instagram_reels": "9:16",
    "naver_place": "1:1",
    "blog": "16:9",
    "banner": "16:9",
    "custom": "1:1",
}

IMAGEN_SIZE_BY_RESOLUTION = {
    "auto": "1:1",
    "512": "1:1",
    "1k": "1:1",
    "2k": "1:1",
    "4k": "1:1",
}

OPENAI_SIZE_BY_CHANNEL = {
    "instagram_feed": "1024x1024",
    "instagram_story": "1024x1536",
    "instagram_reels": "1024x1536",
    "naver_place": "1024x1024",
    "blog": "1536x1024",
    "banner": "1536x1024",
    "custom": "1024x1024",
}

IMAGE_CHANNELS = {
    "instagram": "instagram_feed",
    "instagram_story": "instagram_story",
    "instagram_reels": "instagram_reels",
    "인스타": "instagram_feed",
    "sns": "instagram_feed",
    "SNS": "instagram_feed",
    "blog": "blog",
    "블로그": "blog",
    "naver_place": "naver_place",
    "네이버플레이스": "naver_place",
    "banner": "banner",
    "배너": "banner",
    "general": "custom",
    "custom": "custom",
    "일반": "custom",
}

VISUAL_MOOD_HINTS = {
    "bright": "깨끗하고 밝은 하이키 조명, 선명한 색감",
    "warm_cozy": "따뜻한 색감, 골든아워 조명, 편안하고 초대하는 분위기",
    "moody": "분위기 있는 저조도 조명, 깊이 있는 색감",
    "clean_minimal": "미니멀한 구성, 넉넉한 여백, 중립적인 색감",
    "premium": "고급스러운 질감, 정제된 구도, 세련된 시각 연출",
    "vibrant": "높은 채도, 활기찬 분위기, 강한 색 대비",
}


def route_image_request(request: ImageIntentRequest) -> tuple[ProviderImageRequest, ImageRoutingDecision]:
    routed_requests, candidates = build_intent_routing_plan(request)
    if not candidates:
        raise RequestValidationError("No image model candidates were available for this request")
    if not routed_requests:
        raise RequestValidationError("No provider image request could be built for this request")
    selected = candidates[0]
    routed = routed_requests[0]
    decision = _candidate_to_decision(selected)
    return routed, decision


def build_intent_routing_plan(request: ImageIntentRequest) -> tuple[list[ProviderImageRequest], list[ImageModelCandidate]]:
    candidates = _select_intent_candidates(request)
    routed_requests = [
        _intent_candidate_to_request(request, candidate)
        for candidate in candidates
        if candidate.provider != "local"
    ]
    return routed_requests, candidates


def build_image_routing_plan(request: ImageRequest) -> tuple[list[ProviderImageRequest], list[ImageModelCandidate], str, str]:
    primary_channel = _primary_image_channel(request)
    prompt = _build_final_image_prompt(request, primary_channel)
    negative_prompt = _build_image_request_negative_prompt(request)
    size = CHANNEL_ASPECT_RATIOS[primary_channel]
    openai_size = OPENAI_SIZE_BY_CHANNEL[primary_channel]
    candidates = _select_image_candidates(request, size, openai_size)

    routed_requests = [
        ProviderImageRequest(
            provider=candidate.provider,
            model=candidate.model,
            prompt=prompt,
            reference_images=request.reference_images if candidate.operation == "edit" else None,
            text_to_render=request.text_to_render,
            negative_prompt=negative_prompt if candidate.provider == "google" else None,
            size=candidate.size,
            quality=_default_quality(candidate.provider) if candidate.provider != "local" else "auto",
            output_format="png",
            background="auto",
            style=_to_openai_style(request.visual_mood),
            n=candidate.n,
        )
        for candidate in candidates
        if candidate.provider != "local"
    ]
    return routed_requests, candidates, primary_channel, prompt


def apply_text_free_provider_policy(request: ProviderImageRequest) -> ProviderImageRequest:
    if request.text_to_render or request.model == "gpt-image-2":
        return request
    return request.model_copy(update={"prompt": _append_text_free_visible_writing_policy(request.prompt)})


def apply_text_free_reference_provider_policy(
    request: ProviderImageGenerateWithReferenceRequest,
) -> ProviderImageGenerateWithReferenceRequest:
    if request.text_to_render or request.model == "gpt-image-2":
        return request
    return request.model_copy(update={"prompt": _append_text_free_visible_writing_policy(request.prompt)})


def _primary_image_channel(request: ImageRequest) -> str:
    if not request.channels:
        raise RequestValidationError("channels must include at least one value")
    return _lookup_or_validation_error(IMAGE_CHANNELS, request.channels[0], "image channel")


def _select_image_candidates(
    request: ImageRequest,
    google_size: str,
    openai_size: str,
) -> list[ImageModelCandidate]:
    if _image_request_has_text(request) and request.reference_images:
        return [
            ImageModelCandidate(
                rank=1,
                provider="openai",
                model=_openai_text_accuracy_model(get_settings()),
                operation="edit",
                size=openai_size,
                n=min(request.n, 4),
                reason="Text rendering with a reference image prioritizes GPT Image for Korean text accuracy.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="google",
                model="gemini-2.5-flash-image",
                operation="edit",
                size=google_size,
                n=min(request.n, 4),
                reason="Fallback to Nano Banana for reference-based text insertion if GPT Image fails.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if _image_request_has_text(request):
        return [
            ImageModelCandidate(
                rank=1,
                provider="openai",
                model=_openai_text_accuracy_model(get_settings()),
                operation="generate",
                size=openai_size,
                n=min(request.n, 4),
                reason="Text rendering prioritizes GPT Image for Korean text accuracy.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="google",
                model="gemini-2.5-flash-image",
                operation="generate",
                size=google_size,
                n=min(request.n, 4),
                reason="Fallback to Nano Banana if GPT Image text rendering fails.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if request.reference_images:
        return [
            ImageModelCandidate(
                rank=1,
                provider="google",
                model="gemini-2.5-flash-image",
                operation="edit",
                size=google_size,
                n=min(request.n, 4),
                reason="Reference image is attached, so Nano Banana is the first generate-with-reference option.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="openai",
                model=_openai_edit_model(get_settings()),
                operation="edit",
                size=openai_size,
                n=min(request.n, 4),
                reason="GPT Image is the second option for reference-based editing and text-sensitive correction.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if _is_quality_or_brand_request(request):
        return [
            ImageModelCandidate(
                rank=1,
                provider="google",
                model="gemini-2.5-flash-image",
                operation="generate",
                size=google_size,
                n=min(request.n, 4),
                reason="Brand image generation uses Nano Banana after the Imagen 4 shutdown.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="openai",
                model=_openai_quality_model(get_settings()),
                operation="generate",
                size=openai_size,
                n=min(request.n, 4),
                reason="GPT Image is a cross-provider fallback for high-quality visual generation.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    return [
        ImageModelCandidate(
            rank=1,
            provider="google",
            model="gemini-2.5-flash-image",
            operation="generate",
            size=google_size,
            n=min(request.n, 4),
            reason="General image generation uses Nano Banana after the Imagen 4 shutdown.",
        ),
        ImageModelCandidate(
            rank=2,
            provider="openai",
            model=_openai_standard_model(get_settings()),
            operation="generate",
            size=openai_size,
            n=min(request.n, 4),
            reason="GPT Image is the cross-provider fallback.",
        ),
        _placeholder_candidate(3, google_size, request.n),
    ]


def _placeholder_candidate(rank: int, size: str, n: int) -> ImageModelCandidate:
    return ImageModelCandidate(
        rank=rank,
        provider="local",
        model="default-placeholder",
        operation="placeholder",
        size=size,
        n=min(n, 4),
        reason="All provider options failed, so a local default image is returned to keep the workflow non-blocking.",
    )


def _select_intent_candidates(request: ImageIntentRequest) -> list[ImageModelCandidate]:
    _validate_edit_request(request)
    settings = get_settings()
    has_text = _has_text(request)
    has_references = bool(request.reference_images)
    operation = _resolve_operation(request)
    google_size = _resolve_size(request, "google")
    openai_size = _resolve_size(request, "openai")

    if has_text and has_references:
        return [
            ImageModelCandidate(
                rank=1,
                provider="openai",
                model=_openai_text_accuracy_model(settings),
                operation="edit",
                size=openai_size,
                n=min(request.n, 4),
                reason="Text rendering with a reference image prioritizes GPT Image for Korean text accuracy.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="google",
                model=_default_nano_banana_model(settings),
                operation="edit",
                size=google_size,
                n=min(request.n, 4),
                reason="Fallback to Nano Banana for reference-based text insertion if GPT Image fails.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if has_text:
        return [
            ImageModelCandidate(
                rank=1,
                provider="openai",
                model=_openai_text_accuracy_model(settings),
                operation="generate",
                size=openai_size,
                n=min(request.n, 4),
                reason="Text rendering prioritizes GPT Image for Korean text accuracy.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="google",
                model=_default_nano_banana_model(settings),
                operation="generate",
                size=google_size,
                n=min(request.n, 4),
                reason="Fallback to Nano Banana if GPT Image text rendering fails.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if operation == "edit":
        return [
            ImageModelCandidate(
                rank=1,
                provider="google",
                model=_default_nano_banana_model(settings),
                operation="edit",
                size=google_size,
                n=min(request.n, 4),
                reason="Reference image editing without exact text prioritizes Nano Banana.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="openai",
                model=_openai_edit_model(settings),
                operation="edit",
                size=openai_size,
                n=min(request.n, 4),
                reason="GPT Image is the fallback for reference-based editing.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if request.web_search:
        return [
            ImageModelCandidate(
                rank=1,
                provider="google",
                model=_default_nano_banana_model(settings),
                operation="generate",
                size=google_size,
                n=min(request.n, 4),
                reason="Google search/grounding context is requested.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="openai",
                model=_openai_standard_model(settings),
                operation="generate",
                size=openai_size,
                n=min(request.n, 4),
                reason="GPT Image is the cross-provider fallback.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if request.purpose == "draft" or request.quality_priority in {"cost", "speed"}:
        return [
            ImageModelCandidate(
                rank=1,
                provider="google",
                model=_default_nano_banana_model(settings),
                operation="generate",
                size=google_size,
                n=min(request.n, 4),
                reason="Draft, speed, or cost-priority generation uses Nano Banana after the Imagen 4 shutdown.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="openai",
                model=_openai_fast_model(settings),
                operation="generate",
                size=openai_size,
                n=min(request.n, 4),
                reason="GPT Image Mini is the speed/cost fallback.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    if request.purpose == "final_asset" or request.quality_priority == "quality":
        return [
            ImageModelCandidate(
                rank=1,
                provider="google",
                model=_default_nano_banana_model(settings),
                operation="generate",
                size=google_size,
                n=min(request.n, 4),
                reason="Final or quality-priority generation uses Nano Banana after the Imagen 4 shutdown.",
            ),
            ImageModelCandidate(
                rank=2,
                provider="openai",
                model=_openai_quality_model(settings),
                operation="generate",
                size=openai_size,
                n=min(request.n, 4),
                reason="GPT Image is the quality fallback.",
            ),
            _placeholder_candidate(3, google_size, request.n),
        ]

    return [
        ImageModelCandidate(
            rank=1,
            provider="google",
            model=_default_nano_banana_model(settings),
            operation="generate",
            size=google_size,
            n=min(request.n, 4),
            reason="Standard SNS generation uses Nano Banana after the Imagen 4 shutdown.",
        ),
        ImageModelCandidate(
            rank=2,
            provider="openai",
            model=_openai_standard_model(settings),
            operation="generate",
            size=openai_size,
            n=min(request.n, 4),
            reason="GPT Image is the standard generation fallback.",
        ),
        _placeholder_candidate(3, google_size, request.n),
    ]


def _is_quality_or_brand_request(request: ImageRequest) -> bool:
    return request.purpose in {"brand", "브랜드"}


def _build_final_image_prompt(request: ImageRequest, primary_channel: str) -> str:
    if not _image_request_has_text(request):
        return _build_text_free_image_prompt(request, primary_channel)

    purpose = _normalize_purpose(request.purpose)
    visual_mood = _visual_mood_hint(request.visual_mood)
    prompt = (
        "한국 로컬 사업자를 위한 완성도 높은 마케팅 이미지를 생성하세요.\n"
        "\n[최우선 요청]\n"
        "아래 사용자 이미지 요청을 최우선으로 반영하세요. 목적, 무드, 채널 지시는 이 요청을 보정하는 조건입니다.\n"
        f"{request.image_prompt}\n"
        "\n[마케팅 목적]\n"
        f"{_purpose_instruction(purpose)}\n"
        "\n[시각 무드]\n"
        f"{visual_mood}\n"
        "이 무드는 조명, 색감, 배경, 질감, 카메라 구도에 반영하세요.\n"
        "\n[채널 구도]\n"
        f"주요 출력 채널: {_channel_label(primary_channel)}\n"
        f"{_channel_instruction(primary_channel)}\n"
        "\n[참조 이미지]\n"
        f"{_reference_instruction(request, has_text=True)}\n"
        "\n[텍스트 처리]\n"
        f"{_build_image_request_text_instruction(request)}"
        "\n[품질 기준]\n"
        "흔한 스톡 사진, 과장된 광고 템플릿, 부자연스러운 합성 느낌을 피하세요. "
        "실제 로컬 매장의 마케팅 소재로 바로 사용할 수 있는 자연스럽고 구체적인 이미지를 만드세요."
    )
    return append_visual_safety_guardrails(prompt)


def _build_text_free_image_prompt(request: ImageRequest, primary_channel: str) -> str:
    purpose = _normalize_purpose(request.purpose)
    visual_mood = _visual_mood_hint(request.visual_mood)
    prompt = (
        "한국 로컬 사업자를 위한 자연스러운 실사 마케팅 이미지를 생성하세요.\n"
        "\n[최우선 요청]\n"
        "아래 사용자 이미지 요청을 최우선으로 반영하세요. 목적, 무드, 채널 지시는 이 요청을 보정하는 조건입니다.\n"
        f"{request.image_prompt}\n"
        "\n[마케팅 목적]\n"
        f"{_purpose_instruction(purpose)}\n"
        "\n[시각 무드]\n"
        f"{visual_mood}\n"
        "이 무드는 조명, 색감, 배경, 질감, 카메라 구도에 반영하세요.\n"
        "\n[채널 구도]\n"
        f"주요 출력 채널: {_channel_label(primary_channel)}\n"
        f"{_visual_composition_instruction(primary_channel)}\n"
        f"{_channel_instruction(primary_channel)}\n"
        "\n[참조 이미지]\n"
        f"{_reference_instruction(request, has_text=False)}\n"
        f"\n{_text_free_visible_writing_policy()}\n"
        "\n[품질 기준]\n"
        "사용자가 설명한 실제 장면, 사람, 사물, 공간, 조명, 분위기를 우선하세요. "
        "템플릿형 그래픽 레이아웃, UI 목업, 프로필형 카드, 관련 없는 인물 중심 구도는 피하세요. "
        "실제 로컬 매장의 마케팅 소재로 바로 사용할 수 있는 자연스럽고 구체적인 이미지를 만드세요."
    )
    return append_visual_safety_guardrails(prompt)


def _build_image_request_text_instruction(request: ImageRequest) -> str:
    safety_note = "렌더링할 문구도 GAIM 마케팅 안전 정책과 시각 콘텐츠 안전 정책을 따라야 합니다. "
    if request.text_rendering:
        parts = [
            "다음 문구를 이미지 안에 정확히 렌더링하세요: ",
            f"{request.text_rendering.text}. ",
            safety_note,
            f"언어: {request.text_rendering.language}. ",
            f"배치: {request.text_rendering.placement}. ",
        ]
        if request.text_rendering.font_hint:
            parts.append(f"폰트 힌트: {request.text_rendering.font_hint}. ")
        if request.text_rendering.color_hint:
            parts.append(f"색상 힌트: {request.text_rendering.color_hint}. ")
        return "".join(parts) + "\n"
    if request.text_to_render:
        return f"다음 문구를 이미지 안에 정확히 렌더링하세요: {request.text_to_render}. {safety_note}\n"
    return ""


def _build_image_request_negative_prompt(request: ImageRequest) -> str | None:
    return None


def _text_free_visible_writing_policy() -> str:
    return (
        "[Visible writing policy]\n"
        "If visible words, signage, labels, menus, posters, banners, stickers, packaging text, "
        "or UI-like marks naturally appear in the scene, render them only as short, common English words. "
        "Korean writing must not appear. Avoid pseudo-Korean or unreadable Korean-like glyphs."
    )


def _append_text_free_visible_writing_policy(prompt: str) -> str:
    if "[Visible writing policy]" in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{_text_free_visible_writing_policy()}"


def _normalize_purpose(value: str) -> str:
    return _lookup_or_validation_error({
        "promotion": "홍보",
        "홍보": "홍보",
        "event": "이벤트",
        "이벤트": "이벤트",
        "brand": "브랜드",
        "브랜드": "브랜드",
    }, value, "image purpose")


def _purpose_instruction(purpose: str) -> str:
    return _lookup_or_validation_error({
        "홍보": "목적은 홍보입니다. 상품이나 서비스의 매력을 즉시 알아볼 수 있게 표현하고, 방문 또는 구매 욕구가 생기도록 핵심 피사체를 분명히 보여주세요.",
        "이벤트": "목적은 이벤트입니다. 혜택, 시즌감, 한정성, 활기 있는 분위기가 느껴지게 표현하고, 사용자가 행사에 참여하고 싶도록 장면을 구성하세요.",
        "브랜드": "목적은 브랜드입니다. 공간, 품질, 신뢰감, 브랜드 정체성이 드러나게 표현하고, 과장된 판촉보다 정돈되고 일관된 인상을 우선하세요.",
    }, purpose, "image purpose")


def _visual_mood_hint(value: str) -> str:
    return _lookup_or_validation_error(VISUAL_MOOD_HINTS, value, "visual mood")


def _to_openai_style(value: str) -> str:
    return "vivid" if value in {"bright", "vibrant"} else "natural"


def _visual_composition_instruction(primary_channel: str) -> str:
    return _lookup_or_validation_error({
        "instagram_feed": "중앙 주제가 명확한 정사각형 크롭을 사용하세요.",
        "instagram_story": "주요 피사체가 잘 보이는 균형 잡힌 세로형 크롭을 사용하세요.",
        "instagram_reels": "시각적 초점이 강한 균형 잡힌 세로형 크롭을 사용하세요.",
        "naver_place": "상품이나 매장이 명확히 보이는 정사각형 크롭을 사용하세요.",
        "blog": "공간과 분위기를 강조하는 넓은 에디토리얼 크롭을 사용하세요.",
        "banner": "자연스러운 여백이 있는 넓은 크롭을 사용하세요.",
        "custom": "균형 잡힌 정사각형 크롭을 사용하세요.",
    }, primary_channel, "primary image channel")


def _channel_instruction(primary_channel: str) -> str:
    return _lookup_or_validation_error({
        "instagram_feed": "정사각형 SNS 피드에서 작은 썸네일로 보아도 핵심 피사체가 바로 식별되게 하세요. 중앙 피사체와 주변 여백의 균형을 유지하세요.",
        "instagram_story": "9:16 세로형 모바일 화면을 기준으로 구성하세요. 상하단 UI 오버레이를 피할 안전 여백을 두고, 핵심 피사체는 중앙 또는 상단 2/3 안에 배치하세요.",
        "instagram_reels": "9:16 세로형 짧은 영상 커버처럼 강한 첫인상을 주도록 구성하세요. 핵심 피사체를 크게 보이게 하되 상하단 UI 오버레이를 피할 여백을 확보하세요.",
        "naver_place": "로컬 비즈니스 목록에서 상품이나 매장이 분명히 보이도록 깔끔하게 구성하세요. 과도한 연출보다 실제 방문 판단에 도움이 되는 정보를 시각적으로 드러내세요.",
        "blog": "블로그 헤더나 본문 이미지에 어울리도록 넓은 배경과 공간감을 살리세요. 분위기와 맥락이 읽히는 안정적인 가로 구도를 사용하세요.",
        "banner": "가로형 배너로 사용할 수 있게 좌우 또는 한쪽에 자연스러운 여백을 확보하세요. 피사체와 빈 공간의 균형을 유지하세요.",
        "custom": "범용 마케팅 소재로 쓰기 좋게 핵심 피사체, 배경, 여백의 균형을 유지하세요.",
    }, primary_channel, "primary image channel")


def _channel_label(primary_channel: str) -> str:
    return _lookup_or_validation_error({
        "instagram_feed": "인스타그램 피드",
        "instagram_story": "인스타그램 스토리",
        "instagram_reels": "인스타그램 릴스",
        "naver_place": "네이버플레이스",
        "blog": "블로그",
        "banner": "배너",
        "custom": "일반",
    }, primary_channel, "primary image channel")


def _reference_instruction(request: ImageRequest, has_text: bool) -> str:
    if not request.reference_images:
        return "참조 이미지가 없으므로 사용자 이미지 요청과 목적, 무드, 채널 구도를 기준으로 새 이미지를 생성하세요."
    if has_text:
        return (
            "첨부된 참조 이미지를 상품, 공간, 분위기, 구도의 시각적 가이드로 사용하세요. "
            "참조 이미지의 핵심 특징을 유지하되 새로운 마케팅 이미지로 자연스럽게 재구성하고, 텍스트 처리 지시에 따라 문구를 정확히 넣으세요."
        )
    return (
        "첨부된 참조 이미지를 상품, 공간, 분위기, 구도의 시각적 가이드로만 사용하세요. "
        "참조 이미지의 핵심 특징은 유지하되 새 마케팅 이미지처럼 자연스럽게 재구성하세요."
    )


def _resolve_operation(request: ImageIntentRequest) -> str:
    has_references = bool(request.reference_images)

    if has_references:
        return "edit"
    if request.task in EDIT_TASKS and request.task != "text_insert":
        return "edit"
    return "generate"


def _select_model(request: ImageIntentRequest, operation: str, settings) -> tuple[str, str, str]:
    if operation == "edit":
        _validate_edit_request(request)
        if request.text_importance == "high" or request.quality_priority == "text_accuracy":
            return "openai", _openai_text_accuracy_model(settings), "Korean text accuracy or exact text rendering requires GPT Image editing."
        if request.web_search:
            return "google", _default_nano_banana_model(settings), "Google grounding/search context is requested, so Nano Banana is selected."
        return "google", _default_nano_banana_model(settings), "Generate-with-reference workflow is routed to Nano Banana for a lower-cost integrated path."

    if request.web_search:
        return "google", _default_nano_banana_model(settings), "Google search/grounding context is requested."
    if request.text_importance == "high" or request.quality_priority == "text_accuracy":
        return "openai", _openai_text_accuracy_model(settings), "Korean text accuracy or exact text rendering requires GPT Image generation."
    if request.purpose == "draft" or request.quality_priority in {"cost", "speed"}:
        return "google", _default_nano_banana_model(settings), "Draft, speed, or cost-priority generation uses Nano Banana after the Imagen 4 shutdown."
    if request.purpose == "final_asset" or request.quality_priority == "quality":
        return "google", _default_nano_banana_model(settings), "Final or quality-priority generation uses Nano Banana after the Imagen 4 shutdown."
    return "google", _default_nano_banana_model(settings), "Standard SNS generation uses Nano Banana after the Imagen 4 shutdown."


def _intent_candidate_to_request(request: ImageIntentRequest, candidate: ImageModelCandidate) -> ProviderImageRequest:
    return ProviderImageRequest(
        provider=candidate.provider,
        model=candidate.model,
        prompt=_build_prompt(request),
        reference_images=request.reference_images if candidate.operation == "edit" else None,
        text_to_render=request.text_to_render,
        size=candidate.size,
        quality=_default_quality(candidate.provider),
        output_format=_resolve_output_format(request, candidate.provider),
        background=request.background,
        style=request.style,
        n=candidate.n,
    )


def _candidate_to_decision(
    candidate: ImageModelCandidate,
    attempted: list[ImageModelCandidate] | None = None,
    warnings: list[str] | None = None,
) -> ImageRoutingDecision:
    return ImageRoutingDecision(
        provider=candidate.provider,
        model=candidate.model,
        operation=candidate.operation,
        size=candidate.size,
        n=candidate.n,
        reason=candidate.reason,
        attempted_models=attempted or [],
        fallback_used=candidate.rank != 1,
        warnings=warnings or [],
    )


def build_intent_routing_decision(
    candidate: ImageModelCandidate,
    attempted: list[ImageModelCandidate],
    warnings: list[str],
) -> ImageRoutingDecision:
    return _candidate_to_decision(candidate, attempted=attempted, warnings=warnings)


def _validate_edit_request(request: ImageIntentRequest) -> None:
    if request.task in {"inpaint", "outpaint"} and not request.reference_images:
        raise RequestValidationError(f"{request.task} requires reference_images")


def _has_text(request: ImageIntentRequest) -> bool:
    return bool(request.text_rendering or request.text_to_render)


def _image_request_has_text(request: ImageRequest) -> bool:
    return bool(request.text_rendering or request.text_to_render)


def _resolve_size(request: ImageIntentRequest, provider: str) -> str:
    if request.size:
        return request.size
    aspect_ratio = request.aspect_ratio or _lookup_or_validation_error(CHANNEL_ASPECT_RATIOS, request.channel, "image channel")
    if provider == "google":
        return aspect_ratio
    return _lookup_or_validation_error(OPENAI_SIZE_BY_CHANNEL, request.channel, "image channel")


def _lookup_or_validation_error(mapping: dict[str, str], key: str, label: str) -> str:
    value = mapping.get(key)
    if value is None:
        raise RequestValidationError(f"Unsupported {label}: {key}")
    return value


def _resolve_image_count(request: ImageIntentRequest, model: str) -> int:
    if model in NANO_BANANA_MODELS:
        return min(request.n, 4)
    return min(request.n, 10)


def _resolve_output_format(request: ImageIntentRequest, provider: str) -> str:
    if provider == "google":
        return "png"
    return request.output_format


def _default_quality(provider: str) -> str:
    if provider == "google":
        return "auto"
    return get_settings().openai_default_image_quality


def _default_nano_banana_model(settings) -> str:
    if settings.google_default_image_model in NANO_BANANA_MODELS:
        return settings.google_default_image_model
    return "gemini-2.5-flash-image"


def _openai_quality_model(settings) -> str:
    return _select_configured_openai_model(
        settings.openai_quality_image_model,
        OPENAI_IMAGE_QUALITY_MODELS,
        "gpt-image-2",
    )


def _openai_standard_model(settings) -> str:
    return _select_configured_openai_model(
        settings.openai_standard_image_model,
        OPENAI_IMAGE_STANDARD_MODELS,
        "gpt-image-1.5",
    )


def _openai_fast_model(settings) -> str:
    return _select_configured_openai_model(
        settings.openai_fast_image_model,
        OPENAI_IMAGE_FAST_MODELS,
        "gpt-image-1-mini",
    )


def _openai_edit_model(settings) -> str:
    return _select_configured_openai_model(
        settings.openai_edit_image_model,
        OPENAI_IMAGE_EDIT_MODELS,
        "gpt-image-2",
    )


def _openai_text_accuracy_model(settings) -> str:
    return _select_configured_openai_model(
        settings.openai_text_accuracy_image_model,
        OPENAI_IMAGE_QUALITY_MODELS,
        "gpt-image-2",
    )


def _select_configured_openai_model(configured: str, allowed_models: set[str], fallback: str) -> str:
    if configured in allowed_models:
        return configured
    return fallback


def openai_default_generate_model() -> str:
    return _openai_standard_model(get_settings())


def openai_default_edit_model() -> str:
    return _openai_edit_model(get_settings())


def _build_prompt(request: ImageIntentRequest) -> str:
    parts = [request.prompt]
    safety_note = "렌더링할 문구도 GAIM 마케팅 안전 정책과 시각 콘텐츠 안전 정책을 따라야 합니다."
    if request.text_rendering:
        parts.append(
            "다음 문구를 정확히 렌더링하세요: "
            f"{request.text_rendering.text}. "
            f"{safety_note} "
            f"언어: {request.text_rendering.language}. "
            f"배치: {request.text_rendering.placement}."
        )
        if request.text_rendering.font_hint:
            parts.append(f"폰트 힌트: {request.text_rendering.font_hint}.")
        if request.text_rendering.color_hint:
            parts.append(f"색상 힌트: {request.text_rendering.color_hint}.")
    elif request.text_to_render:
        parts.append(f"다음 문구를 정확히 렌더링하세요: {request.text_to_render}. {safety_note}")
    else:
        parts.append(_text_free_visible_writing_policy())
    return append_visual_safety_guardrails("\n".join(parts))


def validate_routed_request(request: ProviderImageRequest) -> None:
    if request.provider == "openai" and request.model and request.model not in OPENAI_IMAGE_MODELS:
        raise RequestValidationError(f"Unsupported OpenAI image model: {request.model}")
    if request.provider == "google" and request.model in DEPRECATED_IMAGEN_MODELS:
        raise RequestValidationError(
            f"Unsupported Google image model: {request.model}. Imagen 4 was shut down on 2026-08-17."
        )
    if request.provider == "google" and request.model and request.model not in NANO_BANANA_MODELS:
        raise RequestValidationError(f"Unsupported Google image model: {request.model}")
    if request.model in NANO_BANANA_MODELS and request.reference_images and len(request.reference_images) > 14:
        raise RequestValidationError("Nano Banana supports up to 14 reference images")
    if request.provider == "openai" and request.reference_images and len(request.reference_images) > 10:
        raise RequestValidationError("GPT Image edit supports up to 10 reference images")
