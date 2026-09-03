def test_openai_edit_omits_input_fidelity_for_gpt_image_2():
    from app.schemas.image import ProviderImageGenerateWithReferenceRequest, ReferenceImage
    from app.services.image.openai_service import _build_openai_edit_kwargs

    request = ProviderImageGenerateWithReferenceRequest(
        provider="openai",
        model="gpt-image-2",
        prompt="참조 이미지를 기반으로 과일 가게 광고 이미지로 편집해줘",
        reference_images=[
            ReferenceImage(
                b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                mime_type="image/png",
            )
        ],
        size="1024x1024",
        quality="low",
    )

    kwargs = _build_openai_edit_kwargs(request=request, model="gpt-image-2", image_inputs=["image"], quality="low")

    assert "input_fidelity" not in kwargs
    assert "[GAIM 시각 콘텐츠 안전 정책]" in kwargs["prompt"]

def test_openai_edit_keeps_input_fidelity_for_prior_gpt_image_models():
    from app.schemas.image import ProviderImageGenerateWithReferenceRequest, ReferenceImage
    from app.services.image.openai_service import _build_openai_edit_kwargs

    request = ProviderImageGenerateWithReferenceRequest(
        provider="openai",
        model="gpt-image-1.5",
        prompt="참조 이미지를 기반으로 과일 가게 광고 이미지로 편집해줘",
        reference_images=[
            ReferenceImage(
                b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                mime_type="image/png",
            )
        ],
        size="1024x1024",
        quality="low",
    )

    kwargs = _build_openai_edit_kwargs(request=request, model="gpt-image-1.5", image_inputs=["image"], quality="low")

    assert kwargs["input_fidelity"] == "high"

def test_image_routing_prompt_contains_visual_safety_guardrails():
    from app.schemas.image import ImageRequest
    from app.services.image.model_router import build_image_routing_plan

    routed_requests, _, _, final_prompt = build_image_routing_plan(
        ImageRequest(
            purpose="promotion",
            channels=["instagram"],
            image_prompt="따뜻한 카페 라떼 홍보 이미지",
            visual_mood="warm_cozy",
            n=1,
        )
    )

    assert "[GAIM 시각 콘텐츠 안전 정책]" in final_prompt
    assert "[GAIM 시각 콘텐츠 안전 정책]" in routed_requests[0].prompt
    assert final_prompt.count("[GAIM 시각 콘텐츠 안전 정책]") == 1

def test_image_routing_text_rendering_mentions_safety_policy():
    from app.schemas.image import ImageRequest
    from app.services.image.model_router import build_image_routing_plan

    routed_requests, _, _, final_prompt = build_image_routing_plan(
        ImageRequest(
            purpose="promotion",
            channels=["instagram"],
            image_prompt="딸기 케이크 이벤트 이미지",
            visual_mood="bright",
            text_to_render="오늘 딸기 케이크 할인",
            n=1,
        )
    )

    assert "렌더링할 문구도 GAIM 마케팅 안전 정책과 시각 콘텐츠 안전 정책을 따라야 합니다" in final_prompt
    assert "렌더링할 문구도 GAIM 마케팅 안전 정책과 시각 콘텐츠 안전 정책을 따라야 합니다" in routed_requests[0].prompt

def test_text_free_image_prompt_uses_english_visible_writing_policy():
    from app.schemas.image import ImageRequest
    from app.services.image.model_router import build_image_routing_plan

    routed_requests, candidates, _, final_prompt = build_image_routing_plan(
        ImageRequest(
            purpose="event",
            channels=["instagram"],
            image_prompt="봄맞이 이벤트가 열리는 매장 앞에서 사람들이 즐겁게 입장하는 모습, 밝은 햇살, 활기찬 분위기, 자연스러운 실사",
            visual_mood="bright",
            n=1,
        )
    )

    assert candidates[0].model == "gemini-2.5-flash-image"
    assert "[Visible writing policy]" in final_prompt
    assert "render them only as short, common English words" in routed_requests[0].prompt
    assert "Korean writing must not appear" in routed_requests[0].prompt
    assert "pseudo-Korean" in routed_requests[0].prompt
    assert "[텍스트 처리]" not in final_prompt

def test_image_create_routes_promotion_to_ranked_nano_banana():
    import asyncio

    from app.schemas.image import ImageRequest
    from app.services.image.create_service import create_image

    result = asyncio.run(create_image(ImageRequest.model_validate({
        "purpose": "홍보",
        "channels": ["인스타", "SNS"],
        "image_prompt": "신선한 과일을 판매하는 밝고 깔끔한 상점 이미지",
        "visual_mood": "warm_cozy",
        "n": 3,
    })))
    data = result.model_dump()
    assert data["provider"] == "google"
    assert data["routing"]["primary_channel"] == "instagram_feed"
    assert data["routing"]["selected"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["selected_rank"] == 1
    assert data["routing"]["fallback_used"] is False
    assert "신선한 과일을 판매하는 밝고 깔끔한 상점 이미지" in data["routing"]["final_prompt"]
    assert "[최우선 요청]" in data["routing"]["final_prompt"]
    assert "[마케팅 목적]" in data["routing"]["final_prompt"]
    assert "목적은 홍보입니다" in data["routing"]["final_prompt"]
    assert "따뜻한 색감" in data["routing"]["final_prompt"]
    assert "[채널 구도]" in data["routing"]["final_prompt"]
    assert "주요 출력 채널: 인스타그램 피드" in data["routing"]["final_prompt"]
    assert "instagram_feed" not in data["routing"]["final_prompt"]
    assert "[텍스트 처리]" not in data["routing"]["final_prompt"]
    assert "text_rendering" not in data["routing"]["final_prompt"]
    assert "다음 문구를 이미지 안에 정확히 렌더링하세요" not in data["routing"]["final_prompt"]
    assert "[품질 기준]" in data["routing"]["final_prompt"]
    assert "Create a" not in data["routing"]["final_prompt"]

def test_image_create_routes_instagram_story_to_vertical_format():
    import asyncio

    from app.schemas.image import ImageRequest
    from app.services.image.create_service import create_image

    result = asyncio.run(create_image(ImageRequest.model_validate({
        "purpose": "홍보",
        "channels": ["instagram_story"],
        "image_prompt": "신제품 디저트를 소개하는 세로형 스토리 광고 이미지",
        "visual_mood": "bright",
        "n": 1,
    })))
    data = result.model_dump()
    assert data["routing"]["primary_channel"] == "instagram_story"
    assert data["routing"]["selected"]["size"] == "9:16"

def test_image_create_routes_instagram_reels_text_to_openai_vertical_format():
    import asyncio

    from app.schemas.image import ImageRequest
    from app.services.image.create_service import create_image

    result = asyncio.run(create_image(ImageRequest.model_validate({
        "purpose": "홍보",
        "channels": ["instagram_reels"],
        "image_prompt": "신메뉴 출시를 알리는 릴스 커버 이미지",
        "text_to_render": "오늘만 신메뉴 20% 할인",
        "visual_mood": "vibrant",
        "n": 1,
    })))
    data = result.model_dump()
    assert data["provider"] == "openai"
    assert data["routing"]["primary_channel"] == "instagram_reels"
    assert data["routing"]["selected"]["size"] == "1024x1536"

def test_image_create_routes_brand_to_nano_banana():
    import asyncio

    from app.schemas.image import ImageRequest
    from app.services.image.create_service import create_image

    result = asyncio.run(create_image(ImageRequest.model_validate({
        "purpose": "brand",
        "channels": ["banner", "blog"],
        "image_prompt": "프리미엄 과일 선물세트를 소개하는 고급스러운 브랜드 이미지",
        "visual_mood": "premium",
        "n": 4,
    })))
    data = result.model_dump()
    assert data["routing"]["primary_channel"] == "banner"
    assert data["routing"]["selected"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["selected"]["n"] == 4
    assert "목적은 브랜드입니다" in data["routing"]["final_prompt"]
    assert "고급스러운 질감" in data["routing"]["final_prompt"]

def test_image_create_brand_openai_fallback_uses_quality_model():
    from app.schemas.image import ImageRequest
    from app.services.image.model_router import build_image_routing_plan

    request = ImageRequest(
        purpose="brand",
        channels=["banner"],
        image_prompt="프리미엄 브랜드 이미지",
        visual_mood="premium",
        n=2,
    )

    _, candidates, _, _ = build_image_routing_plan(request)
    openai_candidate = next(candidate for candidate in candidates if candidate.provider == "openai")

    assert openai_candidate.model == "gpt-image-2"
    assert openai_candidate.operation == "generate"

def test_image_create_promotion_openai_fallback_uses_standard_model():
    from app.schemas.image import ImageRequest
    from app.services.image.model_router import build_image_routing_plan

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 홍보 이미지",
        visual_mood="warm_cozy",
        n=2,
    )

    _, candidates, _, _ = build_image_routing_plan(request)
    openai_candidate = next(candidate for candidate in candidates if candidate.provider == "openai")

    assert openai_candidate.model == "gpt-image-1.5"
    assert openai_candidate.operation == "generate"

def test_image_create_routes_reference_to_nano_banana():
    import asyncio

    from app.schemas.image import ImageRequest
    from app.services.image.create_service import create_image

    result = asyncio.run(create_image(ImageRequest.model_validate({
        "purpose": "이벤트",
        "channels": ["인스타"],
        "image_prompt": "참조 이미지를 활용해서 과일 가게 봄맞이 이벤트 이미지로 만들어줘",
        "reference_images": [
            {
                "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                "mime_type": "image/png",
            }
        ],
        "visual_mood": "bright",
        "n": 1,
    })))
    data = result.model_dump()
    assert data["routing"]["selected"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["selected"]["operation"] == "edit"
    assert "[참조 이미지]" in data["routing"]["final_prompt"]
    assert "첨부된 참조 이미지를 상품, 공간, 분위기, 구도의 시각적 가이드로만 사용하세요" in data["routing"]["final_prompt"]

def test_image_create_routes_text_to_openai():
    import asyncio

    from app.schemas.image import ImageRequest
    from app.services.image.create_service import create_image

    result = asyncio.run(create_image(ImageRequest.model_validate({
        "purpose": "홍보",
        "channels": ["인스타"],
        "image_prompt": "과일 가게 할인 행사 홍보 이미지",
        "text_rendering": {
            "text": "오늘 딸기 30% 할인",
            "language": "ko",
            "placement": "bottom",
            "must_render_exactly": True,
        },
        "visual_mood": "vibrant",
        "n": 1,
    })))
    data = result.model_dump()
    assert data["provider"] == "openai"
    assert data["routing"]["selected"]["model"] == "gpt-image-2"
    assert data["routing"]["selected"]["operation"] == "generate"
    assert "다음 문구를 이미지 안에 정확히 렌더링하세요" in data["routing"]["final_prompt"]

def test_image_create_routes_reference_text_to_openai_edit():
    import asyncio

    from app.schemas.image import ImageRequest
    from app.services.image.create_service import create_image

    result = asyncio.run(create_image(ImageRequest.model_validate({
        "purpose": "이벤트",
        "channels": ["인스타"],
        "image_prompt": "참조 이미지를 활용해서 과일 가게 이벤트 이미지로 만들어줘",
        "reference_images": [
            {
                "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                "mime_type": "image/png",
            }
        ],
        "text_to_render": "오늘의 신선 과일",
        "visual_mood": "bright",
        "n": 1,
    })))
    data = result.model_dump()
    assert data["provider"] == "openai"
    assert data["routing"]["selected"]["model"] == "gpt-image-2"
    assert data["routing"]["selected"]["operation"] == "edit"
    assert "오늘의 신선 과일" in data["routing"]["final_prompt"]

def test_image_intent_route_rejects_empty_provider_routing(monkeypatch):
    from app.core.exceptions import RequestValidationError
    from app.schemas.image import ImageIntentRequest, ImageModelCandidate
    from app.services.image import model_router

    def local_only_candidates(request):
        return [
            ImageModelCandidate(
                rank=1,
                provider="local",
                model="default-placeholder",
                operation="placeholder",
                size="1:1",
                n=1,
                reason="forced local-only route",
            )
        ]

    monkeypatch.setattr(model_router, "_select_intent_candidates", local_only_candidates)

    request = ImageIntentRequest(prompt="카페 이미지")
    try:
        model_router.route_image_request(request)
    except RequestValidationError as exc:
        assert "No provider image request" in exc.message
    else:
        raise AssertionError("Expected route_image_request to reject empty provider routing")

def test_image_create_text_falls_back_to_nano_banana_when_openai_fails(monkeypatch):
    import asyncio

    from app.core.exceptions import ProviderError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def fail_openai(request):
        raise ProviderError("forced openai failure")

    monkeypatch.setattr(create_service, "generate_openai_images", fail_openai)

    result = asyncio.run(create_service.create_image(ImageRequest.model_validate({
        "purpose": "홍보",
        "channels": ["인스타"],
        "image_prompt": "과일 가게 할인 행사 홍보 이미지",
        "text_to_render": "오늘 딸기 30% 할인",
        "visual_mood": "vibrant",
        "n": 1,
    })))
    data = result.model_dump()
    assert data["provider"] == "google"
    assert data["routing"]["selected"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["fallback_used"] is True
    assert "Korean text accuracy may be lower" in data["routing"]["warnings"][-1]

def test_image_create_returns_placeholder_when_all_providers_fail(monkeypatch):
    import asyncio

    from app.core.exceptions import ProviderError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def fail_provider(request):
        raise ProviderError("forced provider failure")

    monkeypatch.setattr(create_service, "generate_google_images", fail_provider)
    monkeypatch.setattr(create_service, "generate_openai_images", fail_provider)

    result = asyncio.run(create_service.create_image(ImageRequest.model_validate({
        "purpose": "홍보",
        "channels": ["인스타"],
        "image_prompt": "과일 가게 이미지",
        "visual_mood": "warm_cozy",
        "n": 2,
    })))
    data = result.model_dump()
    assert data["provider"] == "local"
    assert data["model_used"] == "default-placeholder"
    assert data["routing"]["fallback_used"] is True
    assert len(data["routing"]["warnings"]) >= 1
