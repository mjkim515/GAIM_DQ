import re
from typing import Any

from app.core.exceptions import RequestValidationError
from app.schemas.text import BrandTextRequest, MarketingTextRequest, RefineTextRequest, TextRequest


CONTENT_INSTRUCTIONS = {
    "sns": "짧고 자연스러운 SNS 홍보 문구를 작성한다.",
    "banner": "배너에 들어갈 간결한 헤드라인과 서브카피를 작성한다.",
    "email": "고객에게 보내는 이메일 본문 형태로 작성한다.",
    "push": "모바일 푸시 알림에 적합한 짧은 문구를 작성한다.",
}

MARKETING_SAFETY_SECTION_TITLE = "[GAIM 마케팅 안전 정책]"
VISUAL_SAFETY_SECTION_TITLE = "[GAIM 시각 콘텐츠 안전 정책]"


def marketing_safety_guardrails() -> str:
    return (
        f"{MARKETING_SAFETY_SECTION_TITLE}\n"
        "- 로컬 비즈니스 광고로 바로 사용할 수 있는 안전하고 사실 기반의 표현만 작성하세요.\n"
        "- 성적·선정적 표현, 노골적 신체 묘사, 미성년자 성적 암시, 과도한 폭력·유혈·자해·범죄 조장, 혐오·차별 표현은 만들지 마세요.\n"
        "- 불법 상품/서비스 홍보, 개인정보 노출, 타인 사칭, 유명인·실존 인물 사칭성 광고, 저작권·상표권 침해 유도는 피하세요.\n"
        "- 의료·금융·법률 효능이나 결과를 보장하지 말고, 확인되지 않은 할인·재고·기간·순위·수상·인증·배송 약속을 만들지 마세요.\n"
        "- 위험하거나 자극적인 요청은 가능한 경우 세련됨, 역동성, 신뢰감, 긴장감 같은 안전한 마케팅 표현으로 순화하세요."
    )


def visual_safety_guardrails() -> str:
    return (
        f"{VISUAL_SAFETY_SECTION_TITLE}\n"
        "- 광고 소재로 안전하게 사용할 수 있는 비성적, 비폭력적, 비혐오적 시각 표현만 사용하세요.\n"
        "- 노골적 신체 노출, 선정적 포즈, 미성년자 성적 암시, 유혈·잔혹 묘사, 자해·범죄 실행 장면을 만들지 마세요.\n"
        "- 실존 인물이나 유명인을 사칭하거나, 타 브랜드의 고유 표식·캐릭터·저작물을 모방하도록 지시하지 마세요.\n"
        "- 위험하거나 자극적인 원문은 제품, 공간, 분위기, 조명, 구도 중심의 안전한 마케팅 장면으로 순화하세요."
    )


def append_visual_safety_guardrails(prompt: str) -> str:
    if VISUAL_SAFETY_SECTION_TITLE in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{visual_safety_guardrails()}"


def build_marketing_prompt(request: TextRequest) -> str:
    business = request.business_info or {}
    business_lines = "\n".join(f"- {key}: {value}" for key, value in business.items())
    instruction = _lookup_prompt_instruction(CONTENT_INSTRUCTIONS, request.content_type, "content_type")
    return (
        f"{_base_instruction('ko')}\n\n"
        "[작성 목표]\n"
        f"{instruction}\n\n"
        "[비즈니스 정보]\n"
        f"{business_lines or '- 제공되지 않음'}\n\n"
        "[최우선 입력]\n"
        f"{request.prompt}\n\n"
        "[작성 기준]\n"
        "제공되지 않은 매장 정보, 혜택, 가격, 운영 사실은 만들지 마세요. 고객이 바로 이해할 수 있는 실용적인 문구로 작성하세요."
    )


BRAND_MODE_INSTRUCTIONS = {
    "profile_summary": "브랜드 프로필에 근거해 매장을 고객에게 소개하는 본문(2~4문장)만 작성한다.",
    "brand_ad_copy": "브랜드의 상시 홍보에 사용할 수 있는 짧은 광고 카피를 작성한다.",
    "brand_image_prompt": "브랜드 기본 이미지 또는 대표 비주얼을 생성하기 위한 이미지 프롬프트를 작성한다.",
}

REFINE_MODE_INSTRUCTIONS = {
    "content_prompt_rewrite": "사용자가 작성한 이미지, 영상 등 콘텐츠 생성 프롬프트를 더 구체적이고 생성 친화적으로 재작성한다.",
    "copy_rewrite": "사용자가 작성한 문구를 목표 채널과 톤에 맞게 다듬는다.",
}

MARKETING_CONTENT_INSTRUCTIONS = {
    "product_detail": "상품 상세페이지에 사용할 수 있는 구매 설득형 설명 문구를 작성한다.",
    "ad_copy": "클릭과 구매 행동을 유도하는 짧은 광고 문구 또는 카피를 작성한다.",
    "sns_post": "선택 목적과 톤에 맞는 SNS 게시글 본문을 작성한다.",
    "customer_message": "문의, 배송, 교환, 리뷰 등 고객 응대에 사용할 수 있는 답변 문구를 작성한다.",
}

MARKETING_PURPOSE_LABELS = {
    "instagram_promotion": "인스타 홍보",
    "blog_promotion": "블로그 홍보",
    "product_detail_page": "상세페이지",
    "ad_click": "광고 클릭 유도",
    "customer_response": "고객 응답",
}

MARKETING_TONE_LABELS = {
    "emotional": "감성적 느낌",
    "practical": "친근하고 실용적인 느낌",
    "premium": "프리미엄 느낌",
    "lively": "활기찬 느낌",
    "professional": "전문적인 느낌",
}

MARKETING_LENGTH_LABELS = {
    "short": "짧게",
    "medium": "보통 길이",
    "long": "자세히",
}

VISUAL_MOOD_LABELS = {
    "bright": "밝고 화사한 무드",
    "warm_cozy": "따뜻하고 아늑한 무드",
    "moody": "감성적이고 깊이 있는 무드",
    "clean_minimal": "깔끔하고 미니멀한 무드",
    "premium": "고급스럽고 정제된 무드",
    "vibrant": "활기차고 생동감 있는 무드",
}

SHORTFORM_PLATFORM_LABELS = {
    "youtube_shorts": "YouTube Shorts",
    "instagram_reels": "Instagram Reels",
    "tiktok": "TikTok",
    "naver_clip": "네이버 클립",
}


def build_brand_prompt(request: BrandTextRequest) -> str:
    visual_rules = (
        "\n\n[시각 콘텐츠 기준]\n"
        + visual_safety_guardrails()
        if request.mode == "brand_image_prompt"
        else ""
    )
    tail = (
        "\n\n[출력 규칙]\n"
        "- 브랜드 소개 본문만 2~4문장으로 작성하세요.\n"
        "- 섹션 제목, 라벨, 불릿, 한 줄 슬로건, 키워드 목록은 포함하지 마세요.\n"
        "- 마크다운 기호, 제목, 키:값 형태의 라벨을 사용하지 마세요.\n"
        "- 제공되지 않은 브랜드 사실을 만들지 마세요."
        if request.mode == "profile_summary"
        else "\n\n[출력 규칙]\n간결한 결과만 작성하세요. 필요한 경우 명확한 라벨을 사용하되, 제공되지 않은 브랜드 사실은 만들지 마세요."
    )
    return (
        _base_instruction(request.language)
        + "\n\n[작업]\n"
        + _lookup_prompt_instruction(BRAND_MODE_INSTRUCTIONS, request.mode, "brand mode")
        + "\n\n[브랜드 정보]\n"
        + _format_model(request.brand)
        + "\n\n[제약 조건]\n"
        + _format_model(request.constraints)
        + visual_rules
        + tail
    )


def build_marketing_text_prompt(request: MarketingTextRequest) -> str:
    input_lines = {
        "content_type": request.content_type,
        "topic": request.input.topic,
        "purpose": _marketing_purpose_label(request.input.purpose),
        "tone": _marketing_tone_label(request.input.tone),
        "target_audience": request.input.target_audience,
        "highlight_points": request.input.highlight_points,
    }
    option_lines = {
        "length": _marketing_length_label(request.options.length),
        "number_of_variations": request.options.number_of_variations,
        "must_include": request.options.must_include,
        "must_avoid": request.options.must_avoid,
        "allow_hashtags": request.options.allow_hashtags,
        "allow_emoji": request.options.allow_emoji,
    }
    return (
        _base_instruction("ko")
        + "\n\n[작업]\n"
        + _lookup_prompt_instruction(MARKETING_CONTENT_INSTRUCTIONS, request.content_type, "marketing content_type")
        + "\n\n[사용자 입력]\n"
        + _format_model(input_lines)
        + "\n\n[출력 옵션]\n"
        + _format_model(option_lines)
        + "\n\n[작성 기준]\n"
        + _marketing_output_rules(request)
    )


def _marketing_output_rules(request: MarketingTextRequest) -> str:
    variation_rule = f"- 결과는 {request.options.number_of_variations}개 변형으로 작성하세요."
    common_rules = [
        variation_rule,
        "- 변형과 변형 사이는 반드시 빈 줄 하나로 구분하세요.",
        "- 제공되지 않은 혜택, 가격, 재고, 배송 가능 여부, 기간, 브랜드 사실은 만들지 마세요.",
        "- 사용자가 입력한 상품/주제와 강조 포인트를 우선 반영하세요.",
        "- 반드시 포함해야 하는 표현은 자연스럽게 포함하고, 피해야 할 표현은 사용하지 마세요.",
        f"- 전체 길이는 '{_marketing_length_label(request.options.length)}' 기준을 따르세요.",
    ]
    if not request.options.allow_hashtags:
        common_rules.append("- 해시태그를 작성하지 마세요.")
    if not request.options.allow_emoji:
        common_rules.append("- 이모지를 사용하지 마세요.")

    type_rules = {
        "product_detail": [
            "- 각 변형은 반드시 다음 두 줄 형식으로 작성하세요:",
            "  슬로건: [상품을 한 문장으로 요약하는 캐치프레이즈]",
            "  본문: [핵심 특징·사용 상황·구매 이유를 담은 설명 문구]",
            "- '슬로건:'과 '본문:' 라벨을 그대로 사용하세요.",
            "- 과장된 최상급 표현보다 구체적인 장점과 고객 이점을 우선하세요.",
        ],
        "ad_copy": [
            "- 각 변형은 반드시 다음 두 줄 형식으로 작성하세요:",
            "  슬로건: [클릭을 부르는 한 줄 광고 카피]",
            "  본문: [구매·방문을 유도하는 짧은 보조 문구]",
            "- '슬로건:'과 '본문:' 라벨을 그대로 사용하세요.",
            "- 모바일 광고에서 빠르게 읽히도록 짧고 선명하게 작성하세요.",
            "- 클릭 또는 구매 행동을 유도하되 허위 긴급감은 만들지 마세요.",
        ],
        "sns_post": [
            "- 각 변형은 반드시 다음 두 줄 형식으로 작성하세요:",
            "  슬로건: [SNS 피드에서 멈추게 만드는 첫 후킹 문구]",
            "  본문: [자연스러운 흐름의 SNS 게시글 본문]",
            "- '슬로건:'과 '본문:' 라벨을 그대로 사용하세요.",
            "- 해시태그는 허용된 경우에만 본문 마지막 줄에 붙이세요.",
        ],
        "customer_message": [
            "- 고객에게 직접 보내는 답변처럼 정중하고 명확하게 작성하세요.",
            "- 라벨이나 제목 없이 답변 문구만 작성하세요.",
            "- 책임 소재, 환불, 배송 보장 등 확인되지 않은 약속은 만들지 마세요.",
        ],
    }
    return "\n".join(
        common_rules + _lookup_prompt_instruction(type_rules, request.content_type, "marketing content_type rules")
    )


def build_refine_prompt(request: RefineTextRequest) -> str:
    brand_context = _format_model(request.brand) if request.brand else "- 제공되지 않음"
    if request.mode == "content_prompt_rewrite":
        shortform_rules = _format_shortform_refine_rules(request)
        image_rules = _format_image_prompt_refine_rules(request)
        return (
            _base_instruction(request.language)
            + "\n\n[작업]\n"
            + _lookup_prompt_instruction(REFINE_MODE_INSTRUCTIONS, request.mode, "refine mode")
            + "\n\n[최우선 입력]\n"
            + request.input.text
            + "\n\n[브랜드 정보]\n"
            + brand_context
            + "\n\n[브랜드 정보 사용 경계]\n"
            + "브랜드 정보는 톤, 관점, 품질 기준을 잡기 위한 내부 참고 정보입니다.\n"
            + "사용자가 명시하지 않았다면 브랜드명, 로고, 슬로건, 자막, 오버레이, 화면 속 표시 문구로 추가하지 마세요.\n"
            + "\n\n[목표/채널/형식]\n"
            + _format_model(request.target)
            + shortform_rules
            + image_rules
            + "\n\n[제약 조건]\n"
            + _format_model(request.constraints)
            + "\n\n[출력 규칙]\n"
            + "최종 콘텐츠 생성 프롬프트만 출력하세요.\n"
            + "라벨, 제목, 이유, 설명, 불릿, 따옴표, 마크다운을 포함하지 마세요.\n"
            + "'프롬프트 재작성:', '재작성:', '이유:' 같은 말이나 영문 프롬프트 라벨로 시작하지 마세요.\n"
            + "안전 정책, 가드레일, 금지사항 문장을 최종 프롬프트에 직접 쓰지 마세요.\n"
            + "출력은 목표 형식이 가리키는 생성 API 필드에 그대로 넣을 수 있어야 합니다."
        )
    return (
        _base_instruction(request.language)
        + "\n\n[작업]\n"
        + _lookup_prompt_instruction(REFINE_MODE_INSTRUCTIONS, request.mode, "refine mode")
        + "\n\n[최우선 입력]\n"
        + request.input.text
        + "\n\n[브랜드 정보]\n"
        + brand_context
        + "\n\n[목표/채널/형식]\n"
        + _format_model(request.target)
        + "\n\n[제약 조건]\n"
        + _format_model(request.constraints)
        + "\n\n[출력 규칙]\n"
        + "개선된 결과를 중심으로 출력하세요. 설명이 꼭 필요할 때만 아주 짧게 덧붙이세요."
    )


def normalize_refined_content_prompt(request: RefineTextRequest, content: str) -> str:
    if not _is_shortform_video_refine(request):
        return content.strip()
    scene_prompt = _strip_conflicting_shortform_options(content)
    prefix = _shortform_prompt_prefix(request)
    if not scene_prompt:
        return prefix
    return f"{prefix} {scene_prompt}".strip()


def _is_shortform_video_refine(request: RefineTextRequest) -> bool:
    return request.mode == "content_prompt_rewrite" and request.target.format == "shortform_video_prompt"


def _format_shortform_refine_rules(request: RefineTextRequest) -> str:
    if not _is_shortform_video_refine(request):
        return ""
    return (
        "\n\n[숏폼 영상 재작성 기준]\n"
        f"- 선택 플랫폼/채널: {_shortform_platform_label(request)}\n"
        f"- 선택 화면 비율: {request.target.aspect_ratio or '제공되지 않음'}\n"
        "- 영상 길이는 API의 구조화 파라미터로 전달되므로 재작성 프롬프트 본문에 초 단위 길이를 쓰지 마세요.\n"
        "- 재작성 프롬프트 안에는 선택 플랫폼과 화면 비율만 반영하세요.\n"
        "- 선택값과 다른 길이, 비율, 채널을 만들거나 원문에서 유지하지 마세요.\n"
        "- 원문이 선택값과 충돌하면 선택 플랫폼과 화면 비율에 맞게 고쳐 쓰고, 길이 표현은 제거하세요.\n"
        "- 사용자가 명시하지 않은 브랜드명, 로고, 슬로건, 자막, 오버레이, 화면 속 표시 문구를 만들지 마세요.\n"
        "- 장면 안에 표지판, 메뉴, 포스터, 배너, 라벨 같은 표시 요소가 필요하면 짧고 일반적인 영어 알파벳 단어만 사용하세요.\n"
        "- 한국어, 일본어, 중국어, 아랍어, 유사 문자, 읽을 수 없는 글리프처럼 보이는 표시 요소를 만들지 마세요.\n"
        + visual_safety_guardrails()
    )


def _format_image_prompt_refine_rules(request: RefineTextRequest) -> str:
    if request.mode != "content_prompt_rewrite" or request.target.format != "image_prompt":
        return ""
    return (
        "\n\n[이미지 프롬프트 재작성 기준]\n"
        "- 사용자 원문을 최우선으로 유지하되, 이미지 생성 모델이 바로 이해할 수 있게 장면, 피사체, 배경, 조명, 구도를 구체화하세요.\n"
        f"- 선택 채널: {request.target.channel or '제공되지 않음'}\n"
        f"- 선택 화면 비율: {request.target.aspect_ratio or '제공되지 않음'}\n"
        f"- 선택 시각 무드: {_visual_mood_label(request.target.visual_mood)}\n"
        "- 선택 시각 무드는 조명, 색감, 배경 소재, 질감, 카메라 구도에 반영하세요.\n"
        "- 광고 카피, SNS 본문, 해시태그를 만들지 말고 이미지 생성용 프롬프트 한 문단으로만 재작성하세요.\n"
        "- 텍스트 삽입 요청이 명시되지 않았다면 이미지 안에 읽을 수 있는 글자나 가짜 글자를 요구하지 마세요.\n"
        + visual_safety_guardrails()
    )


def _shortform_prompt_prefix(request: RefineTextRequest) -> str:
    parts = []
    platform = _shortform_platform_label(request)
    if platform:
        parts.append(f"{platform}용")
    if request.target.aspect_ratio:
        parts.append(f"{request.target.aspect_ratio} 세로형" if request.target.aspect_ratio == "9:16" else request.target.aspect_ratio)
    parts.append("숏폼 영상")
    parts.append(".")
    return " ".join(parts).replace(" .", ".")


def _shortform_platform_label(request: RefineTextRequest) -> str:
    key = request.target.platform or request.target.channel or ""
    return SHORTFORM_PLATFORM_LABELS.get(key, key)


def _marketing_purpose_label(value: str) -> str:
    return MARKETING_PURPOSE_LABELS.get(value, value)


def _marketing_tone_label(value: str) -> str:
    return MARKETING_TONE_LABELS.get(value, value)


def _marketing_length_label(value: str) -> str:
    return MARKETING_LENGTH_LABELS.get(value, value)


def _strip_conflicting_shortform_options(prompt: str) -> str:
    cleaned = prompt.strip()
    option_patterns = [
        r"(?:YouTube\s+Shorts?|유튜브\s*쇼츠?|쇼츠|Shorts|Instagram\s+Reels?|인스타그램\s*릴스?|릴스|TikTok|틱톡|Naver\s+Clip|네이버\s*클립)\s*용?",
        r"\b(?:\d{1,3})\s*(?:초|seconds?|sec)\s*(?:분량|길이|영상)?",
        r"\b(?:\d{1,3})-second\b\s*(?:video|short)?",
        r"\b(?:9\s*:\s*16|16\s*:\s*9|1\s*:\s*1|4\s*:\s*5)\b\s*(?:세로형|가로형|vertical|horizontal)?",
        r"(?:세로형|가로형)\s*(?:영상|숏폼)?",
        r"\b(?:vertical|horizontal)\s*(?:format|video)?\b",
        r"(?:숏폼\s*영상|세로\s*영상|가로\s*영상)\s*[.。]?",
        r"\b총\s*[.。]?",
        r"(?:마지막(?:\s*에)?\s*)?[^.。!?]*(?:텍스트\s*오버레이|오버레이\s*텍스트|텍스트\s*배치|자막|캡션|문구|글자|글씨)[^.。!?]*[.。!?]?",
        r"[^.。!?]*(?:text\s*overlay|overlay\s*text|subtitle|caption)[^.。!?]*[.。!?]?",
        r"실존\s*인물[^.。!?]*(?:브랜드\s*로고|저작권\s*캐릭터)[^.。!?]*[.。!?]?",
    ]
    for pattern in option_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[,，、]\s*", ", ", cleaned)
    cleaned = re.sub(r"(?:^\s*[,，、]\s*)|(?:\s*[,，、]\s*$)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _base_instruction(language: str) -> str:
    language_label = "한국어" if language == "ko" else "영어"
    return (
        "당신은 로컬 비즈니스 마케팅 콘텐츠를 실무적으로 다듬는 어시스턴트입니다.\n"
        f"출력 언어: {language_label}.\n"
        "결과는 구체적이고 간결하며 고객이 바로 이해할 수 있게 작성하세요.\n\n"
        + marketing_safety_guardrails()
    )


def _format_model(value: Any) -> str:
    if value is None:
        return "- 제공되지 않음"
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    if not value:
        return "- 제공되지 않음"
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            lines.append(f"- {key}: {item}")
        return "\n".join(lines) if lines else "- 제공되지 않음"
    return str(value)


def _visual_mood_label(value: str | None) -> str:
    if not value:
        return "제공되지 않음"
    return VISUAL_MOOD_LABELS.get(value, value)


def _lookup_prompt_instruction(mapping: dict[str, Any], key: str, label: str) -> Any:
    value = mapping.get(key)
    if value is None:
        raise RequestValidationError(f"Unsupported {label}: {key}")
    return value
