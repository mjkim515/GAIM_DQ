def test_marketing_text_prompt_contains_ui_fields():
    from app.schemas.text import MarketingTextRequest
    from app.services.text.prompts import build_marketing_text_prompt

    prompt = build_marketing_text_prompt(
        MarketingTextRequest(
            content_type="sns_post",
            input={
                "topic": "강원도 수제 감자빵",
                "purpose": "instagram_promotion",
                "tone": "emotional",
                "target_audience": "20~30대 여성",
                "highlight_points": ["촉촉한 식감", "국내산 감자"],
            },
            options={
                "length": "short",
                "number_of_variations": 3,
                "must_include": ["국내산 감자"],
                "must_avoid": ["과장 표현"],
                "allow_hashtags": True,
                "allow_emoji": False,
            },
        )
    )

    assert "SNS 게시글 본문" in prompt
    assert "강원도 수제 감자빵" in prompt
    assert "20~30대 여성" in prompt
    assert "촉촉한 식감" in prompt
    assert "국내산 감자" in prompt
    assert "이모지를 사용하지 마세요" in prompt
    assert "[GAIM 마케팅 안전 정책]" in prompt
    assert "확인되지 않은 할인" in prompt

def test_content_prompt_rewrite_prompt_returns_only_content_prompt():
    from app.schemas.text import RefineTextRequest
    from app.services.text.prompts import build_refine_prompt

    prompt = build_refine_prompt(
        RefineTextRequest(
            model="auto",
            mode="content_prompt_rewrite",
            brand={"name": "강릉 커피집", "category": "카페"},
            input={"text": "카페에서 라떼 사진"},
            target={
                "channel": "instagram",
                "tone": "감성적",
                "format": "image_prompt",
                "visualMood": "warm_cozy",
                "aspectRatio": "1:1",
            },
        )
    )

    assert "[이미지 프롬프트 재작성 기준]" in prompt
    assert "선택 시각 무드: 따뜻하고 아늑한 무드" in prompt
    assert "선택 화면 비율: 1:1" in prompt
    assert "최종 콘텐츠 생성 프롬프트만 출력하세요" in prompt
    assert "라벨, 제목, 이유, 설명" in prompt
    assert "프롬프트 재작성:" in prompt
    assert "목표 형식이 가리키는 생성 API 필드에 그대로 넣을 수 있어야 합니다" in prompt
    assert "[GAIM 시각 콘텐츠 안전 정책]" in prompt
    assert "선정적 포즈" in prompt
    assert "Return only" not in prompt

def test_brand_image_prompt_contains_visual_safety_guardrails():
    from app.schemas.text import BrandTextRequest
    from app.services.text.prompts import build_brand_prompt

    prompt = build_brand_prompt(
        BrandTextRequest(
            mode="brand_image_prompt",
            brand={
                "name": "강릉 커피집",
                "category": "카페",
                "location": "강릉 교동",
                "description": "로컬 원두와 수제 디저트를 판매하는 동네 카페",
            },
        )
    )

    assert "[GAIM 마케팅 안전 정책]" in prompt
    assert "[GAIM 시각 콘텐츠 안전 정책]" in prompt

def test_shortform_refine_prompt_contains_visual_safety_guardrails():
    from app.schemas.text import RefineTextRequest
    from app.services.text.prompts import build_refine_prompt

    prompt = build_refine_prompt(
        RefineTextRequest(
            model="auto",
            mode="content_prompt_rewrite",
            input={"text": "강렬한 제품 숏폼"},
            target={
                "platform": "instagram_reels",
                "format": "shortform_video_prompt",
                "aspectRatio": "9:16",
                "durationSeconds": 8,
            },
        )
    )

    assert "[숏폼 영상 재작성 기준]" in prompt
    assert "[GAIM 시각 콘텐츠 안전 정책]" in prompt
    assert "비성적, 비폭력적, 비혐오적" in prompt
    assert "영상 길이는 API의 구조화 파라미터로 전달" in prompt
    assert "재작성 프롬프트 본문에 초 단위 길이를 쓰지 마세요" in prompt

def test_shortform_refine_normalization_removes_duration_wording():
    from app.schemas.text import RefineTextRequest
    from app.services.text.prompts import normalize_refined_content_prompt

    request = RefineTextRequest(
        model="auto",
        mode="content_prompt_rewrite",
        input={"text": "가을 매장 숏폼"},
        target={
            "platform": "youtube_shorts",
            "format": "shortform_video_prompt",
            "aspectRatio": "9:16",
            "durationSeconds": 8,
        },
    )

    prompt = normalize_refined_content_prompt(
        request,
        "YouTube Shorts용 9:16 세로형 숏폼 영상 4초 분량. 가을 낙엽이 흩날리는 로컬 매장 앞 거리",
    )

    assert prompt.startswith("YouTube Shorts용 9:16 세로형 숏폼 영상.")
    assert "4초" not in prompt
    assert "8초" not in prompt

def test_gpt_5_text_completion_uses_max_completion_tokens():
    from app.services.text.openai_service import _build_chat_completion_kwargs

    kwargs = _build_chat_completion_kwargs("테스트", "gpt-5.5", 300)

    assert kwargs["model"] == "gpt-5.5"
    assert kwargs["max_completion_tokens"] == 300
    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs

def test_gpt_4o_text_completion_keeps_max_tokens():
    from app.services.text.openai_service import _build_chat_completion_kwargs

    kwargs = _build_chat_completion_kwargs("테스트", "gpt-4o-mini", 300)

    assert kwargs["model"] == "gpt-4o-mini"
    assert "GAIM 마케팅 안전 정책" in kwargs["messages"][0]["content"]
    assert kwargs["max_tokens"] == 300
    assert kwargs["temperature"] == 0.8
    assert "max_completion_tokens" not in kwargs
