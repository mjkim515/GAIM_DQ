def test_text_requires_internal_token(client):
    response = client.post("/v1/text/generate", json={"prompt": "카페 홍보 문구"})
    assert response.status_code == 422

def test_text_generate(client, auth_headers):
    response = client.post(
        "/v1/text/generate",
        headers=auth_headers,
        json={
            "prompt": "카페 홍보 문구",
            "content_type": "sns",
            "business_info": {"name": "강릉 커피집"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "강릉 커피집" in data["content"]
    assert data["model_used"].startswith("mock:")

def test_text_brand_generates_from_brand_profile(client, auth_headers):
    response = client.post(
        "/v1/text/brand",
        headers=auth_headers,
        json={
            "model": "gpt-4o-mini",
            "mode": "profile_summary",
            "brand": {
                "name": "강릉 커피집",
                "category": "카페",
                "location": "강릉 교동",
                "description": "로컬 원두와 수제 디저트를 판매하는 동네 카페",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "강릉 커피집" in data["content"]
    assert data["model_used"] == "mock:gpt-4o-mini"

def test_text_marketing_generates_ad_copy(client, auth_headers):
    response = client.post(
        "/v1/text/marketing",
        headers=auth_headers,
        json={
            "content_type": "ad_copy",
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
                "must_include": ["국내산 감자"],
                "must_avoid": ["전국 1등"],
                "allow_hashtags": False,
                "allow_emoji": False,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "강원도 수제 감자빵" in data["content"]
    assert data["model_used"] == "mock:gpt-4o-mini"

def test_text_refine_rewrites_content_prompt_with_auto_quality_model(client, auth_headers):
    response = client.post(
        "/v1/text/refine",
        headers=auth_headers,
        json={
            "model": "auto",
            "mode": "content_prompt_rewrite",
            "brand": {"name": "강릉 커피집", "category": "카페"},
            "input": {"text": "카페에서 라떼 사진"},
            "target": {
                "channel": "instagram",
                "tone": "감성적",
                "format": "image_prompt",
                "visualMood": "warm_cozy",
                "aspectRatio": "1:1",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "카페에서 라떼 사진" in data["content"]
    assert "warm_cozy 무드" in data["content"]
    assert data["model_used"] == "mock:gpt-5.5"
