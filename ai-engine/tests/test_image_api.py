def test_image_generate_stores_local_file(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate",
        headers=auth_headers,
        json={"provider": "openai", "prompt": "바다가 보이는 카페", "n": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openai"
    assert data["model_used"] == "mock:gpt-image-1.5"
    assert data["images"][0].startswith("http://testserver/generated/images/")

def test_image_status_endpoint_reads_celery_result_payload(client, auth_headers, monkeypatch):
    from app.api.v1 import image as image_api

    monkeypatch.setattr(image_api, "celery_result_payload_for_job", lambda job_type, job_id: {
        "jobId": job_id,
        "status": "completed",
        "images": ["http://testserver/generated/images/result.png"],
        "provider": "google",
        "modelUsed": "gemini-2.5-flash-image",
        "durationMs": 1234,
        "progressPct": 100,
    })

    response = client.get("/v1/image/status/reconciler-image-job", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["jobId"] == "reconciler-image-job"
    assert data["status"] == "completed"
    assert data["images"] == ["http://testserver/generated/images/result.png"]
    assert data["provider"] == "google"
    assert data["modelUsed"] == "gemini-2.5-flash-image"
    assert data["durationMs"] == 1234
    assert data["progressPct"] == 100

def test_image_models(client, auth_headers):
    response = client.get("/v1/image/models", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openai"
    assert data["default_model"] == "gpt-image-1.5"
    assert "gpt-image-2" in data["supported_models"]
    assert "1024x1024" in data["supported_sizes"]

def test_openai_generate_with_reference_uses_edit_default_when_model_is_omitted(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate-with-reference",
        headers=auth_headers,
        json={
            "provider": "openai",
            "prompt": "참조 이미지를 기반으로 과일 가게 광고 이미지로 편집해줘",
            "reference_images": [
                {
                    "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                    "mime_type": "image/png",
                }
            ],
            "size": "1024x1024",
            "quality": "low",
            "output_format": "png",
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model_used"] == "mock:gpt-image-2"

def test_google_image_models(client, auth_headers):
    response = client.get("/v1/image/models?provider=google", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "google"
    assert data["default_model"] == "gemini-2.5-flash-image"
    assert "imagen-4.0-generate-001" not in data["supported_models"]
    assert "gemini-3-pro-image-preview" not in data["supported_models"]
    assert "gemini-2.5-flash-image" in data["supported_models"]

def test_google_image_generate_accepts_nano_banana(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate",
        headers=auth_headers,
        json={
            "provider": "google",
            "model": "gemini-2.5-flash-image",
            "prompt": "신선한 과일을 판매하는 상점이미지를 만들어봐",
            "size": "auto",
            "quality": "auto",
            "output_format": "png",
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model_used"] == "mock:gemini-2.5-flash-image"

def test_google_image_generate_rejects_imagen_4(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate",
        headers=auth_headers,
        json={
            "provider": "google",
            "model": "imagen-4.0-generate-001",
            "prompt": "신선한 과일을 판매하는 상점이미지를 만들어봐",
            "size": "1:1",
            "quality": "auto",
            "output_format": "png",
            "n": 1,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "REQUEST_VALIDATION_ERROR"
    assert "Imagen 4 was shut down on 2026-08-17" in data["message"]

def test_openai_image_edit_accepts_reference_and_text(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate-with-reference",
        headers=auth_headers,
            json={
                "provider": "openai",
                "model": "gpt-image-2",
                "prompt": "참조 이미지를 기반으로 과일 가게 광고 이미지로 편집해줘",
                "reference_images": [
                {
                    "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                    "mime_type": "image/png",
                }
            ],
            "text_to_render": "오늘의 신선 과일",
            "size": "1024x1024",
            "quality": "low",
            "output_format": "png",
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model_used"] == "mock:gpt-image-2"

def test_google_image_edit_accepts_reference_and_text(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate-with-reference",
        headers=auth_headers,
        json={
            "provider": "google",
            "model": "gemini-2.5-flash-image",
            "prompt": "참조 이미지를 기반으로 과일 가게 광고 이미지로 편집해줘",
            "reference_images": [
                {
                    "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                    "mime_type": "image/png",
                }
            ],
            "text_to_render": "오늘의 신선 과일",
            "size": "auto",
            "quality": "auto",
            "output_format": "png",
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model_used"] == "mock:gemini-2.5-flash-image"

def test_generate_routes_to_edit_when_reference_images_exist(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate",
        headers=auth_headers,
        json={
            "provider": "google",
            "model": "gemini-2.5-flash-image",
            "prompt": "참조 이미지를 기반으로 과일 가게 광고 이미지로 만들어줘",
            "reference_images": [
                {
                    "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                    "mime_type": "image/png",
                }
            ],
            "text_to_render": "오늘의 신선 과일",
            "size": "auto",
            "quality": "auto",
            "output_format": "png",
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model_used"] == "mock:gemini-2.5-flash-image"

def test_reference_image_requires_single_source(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate-with-reference",
        headers=auth_headers,
        json={
            "provider": "google",
            "prompt": "편집해줘",
            "reference_images": [{"image_url": "http://example.com/a.png", "b64_json": "abc"}],
        },
    )
    assert response.status_code == 422

def test_image_generate_accepts_gpt_image_2_options(client, auth_headers):
    response = client.post(
        "/v1/image/provider-generate",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-image-2",
            "prompt": "신선한 과일을 판매하는 상점이미지를 만들어봐",
            "size": "1024x1024",
            "quality": "low",
            "output_format": "png",
            "background": "auto",
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model_used"] == "mock:gpt-image-2"

def test_image_intent_routes_draft_to_nano_banana(client, auth_headers):
    response = client.post(
        "/v1/image/intent",
        headers=auth_headers,
        json={
            "task": "generate",
            "purpose": "draft",
            "channel": "instagram_feed",
            "quality_priority": "cost",
            "text_importance": "low",
            "prompt": "신선한 과일을 판매하는 밝고 깔끔한 상점 이미지",
            "n": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "google"
    assert data["routing"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["operation"] == "generate"
    assert data["routing"]["n"] == 3

def test_image_intent_routes_final_asset_to_nano_banana(client, auth_headers):
    response = client.post(
        "/v1/image/intent",
        headers=auth_headers,
        json={
            "task": "generate",
            "purpose": "final_asset",
            "channel": "banner",
            "quality_priority": "quality",
            "prompt": "프리미엄 과일 선물세트 포스터",
            "n": 4,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["routing"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["n"] == 4
    assert data["routing"]["size"] == "16:9"

def test_image_intent_routes_exact_korean_text_to_openai(client, auth_headers):
    response = client.post(
        "/v1/image/intent",
        headers=auth_headers,
        json={
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
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openai"
    assert data["routing"]["model"] == "gpt-image-2"
    assert data["routing"]["operation"] == "generate"

def test_image_intent_routes_reference_edit_to_nano_banana(client, auth_headers):
    response = client.post(
        "/v1/image/intent",
        headers=auth_headers,
        json={
            "task": "edit",
            "purpose": "sns_post",
            "channel": "instagram_story",
            "quality_priority": "cost",
            "text_importance": "medium",
            "prompt": "참조 이미지를 과일 가게 인스타그램 스토리 광고로 편집해줘",
            "reference_images": [
                {
                    "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                    "mime_type": "image/png",
                }
            ],
            "text_to_render": "오늘의 신선 과일",
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openai"
    assert data["routing"]["model"] == "gpt-image-2"
    assert data["routing"]["operation"] == "edit"
    assert data["routing"]["size"] == "1024x1536"

def test_image_intent_routes_reference_edit_without_text_to_nano_banana(client, auth_headers):
    response = client.post(
        "/v1/image/intent",
        headers=auth_headers,
        json={
            "task": "edit",
            "purpose": "sns_post",
            "channel": "instagram_story",
            "quality_priority": "cost",
            "text_importance": "medium",
            "prompt": "참조 이미지를 과일 가게 인스타그램 스토리 광고로 편집해줘",
            "reference_images": [
                {
                    "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                    "mime_type": "image/png",
                }
            ],
            "n": 1,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "google"
    assert data["routing"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["operation"] == "edit"
    assert data["routing"]["size"] == "9:16"

def test_image_intent_text_falls_back_to_nano_banana_when_openai_fails(client, auth_headers, monkeypatch):
    from app.core.exceptions import ProviderError
    from app.api.v1 import image as image_api

    async def fail_openai(request):
        raise ProviderError("forced openai failure")

    monkeypatch.setattr(image_api, "generate_openai_images", fail_openai)

    response = client.post(
        "/v1/image/intent",
        headers=auth_headers,
        json={
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
    )
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "google"
    assert data["routing"]["model"] == "gemini-2.5-flash-image"
    assert data["routing"]["fallback_used"] is True
    assert len(data["routing"]["attempted_models"]) == 2
    assert "Korean text accuracy may be lower" in data["routing"]["warnings"][-1]

def test_image_intent_rejects_inpaint_without_reference(client, auth_headers):
    response = client.post(
        "/v1/image/intent",
        headers=auth_headers,
        json={
            "task": "inpaint",
            "purpose": "sns_post",
            "channel": "instagram_feed",
            "prompt": "배경 일부를 수정해줘",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"
