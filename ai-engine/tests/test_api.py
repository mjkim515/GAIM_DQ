def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["storage_backend"] == "local"


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


def test_openapi_image_create_schemas_are_listed_before_test_schemas(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema_names = set(response.json()["components"]["schemas"])
    assert "ImageJobRequest" in schema_names
    assert "ImageJobResponse" in schema_names
    assert "ProviderImageRequest" in schema_names
    assert "ImageIntentRequest" in schema_names
    assert "ImageCreateResponse" not in schema_names


def test_swagger_public_urls_follow_local_and_production_requests():
    from starlette.requests import Request

    from app.main import _public_url_parts

    def build_request(headers):
        return Request({
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/openapi.json",
            "root_path": "",
            "query_string": b"",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "server": ("127.0.0.1", 8002),
            "client": ("127.0.0.1", 50000),
        })

    local = build_request({"host": "127.0.0.1:8002"})
    production = build_request({
        "host": "ai.idq.co.kr",
        "x-forwarded-host": "ai.idq.co.kr",
        "x-forwarded-proto": "https",
    })

    assert _public_url_parts(local) == ("http://127.0.0.1:8002", "")
    assert _public_url_parts(production) == ("https://ai.idq.co.kr", "/gaim")


def test_video_short_generates_mock_job_with_camel_case_body(client, auth_headers):
    response = client.post(
        "/v1/video/jobs",
        headers=auth_headers,
        json={
            "jobId": "test-short-job-1",
            "prompt": "A vertical short ad for a local cafe latte",
            "model": "fast",
            "platform": "instagram_reels",
            "task": "textToVideo",
            "aspectRatio": "9:16",
            "durationSeconds": 8,
            "advanced": {
                "sampleCount": 2,
                "generateAudio": True,
            },
            "metadata": {"campaignId": "campaign-1"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["jobId"] == "test-short-job-1"
    assert "task=textToVideo" in data["message"]

    status_response = client.get(f"/v1/video/status/{data['jobId']}", headers=auth_headers)
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] == "failed"
    assert status_data["videoUrl"] is None
    assert "Mock video generation does not create playable MP4" in status_data["error"]


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


def test_video_status_endpoint_falls_back_to_celery_result_payload(client, auth_headers, monkeypatch):
    from app.services.video import veo_service

    job_id = "reconciler-video-job"
    veo_service._JOBS.pop(job_id, None)
    veo_service._JOB_UPDATED_AT.pop(job_id, None)
    monkeypatch.setattr(veo_service, "celery_result_payload_for_job", lambda job_type, current_job_id: {
        "jobId": current_job_id,
        "status": "completed",
        "videoUrl": "http://testserver/generated/videos/result.mp4",
        "provider": "google",
        "modelUsed": "veo-3.1-fast-generate-001",
        "fallbackUsed": False,
        "warnings": [],
        "durationMs": 2345,
        "progressPct": 100,
    })

    response = client.get(f"/v1/video/status/{job_id}", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["jobId"] == job_id
    assert data["status"] == "completed"
    assert data["videoUrl"] == "http://testserver/generated/videos/result.mp4"
    assert data["provider"] == "google"
    assert data["modelUsed"] == "veo-3.1-fast-generate-001"
    assert data["durationMs"] == 2345
    assert data["progressPct"] == 100


def test_video_short_duplicate_job_id_is_not_enqueued_twice(monkeypatch):
    import asyncio

    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service
    from app.workers.tasks import video_tasks

    job_id = "duplicate-video-job"
    veo_service._JOBS.pop(job_id, None)
    veo_service._JOB_UPDATED_AT.pop(job_id, None)
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(video_tasks.generate_video_short_task, "apply_async", capture_enqueue)
    request = VideoShortCreateRequest.model_validate({
        "jobId": job_id,
        "prompt": "A single video should be generated",
        "model": "fast",
        "task": "textToVideo",
        "aspectRatio": "9:16",
        "durationSeconds": 4,
    })

    async def enqueue_twice():
        first_response = await veo_service.enqueue_video_short_generation(request)
        second_response = await veo_service.enqueue_video_short_generation(request)
        return first_response, second_response

    first, second = asyncio.run(enqueue_twice())

    assert first.status.value == "queued"
    assert second.status.value == "queued"
    assert "이미 등록된 jobId" in second.message
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "video-queue"


def test_video_short_expired_job_id_can_be_enqueued_again(monkeypatch):
    import asyncio
    import time

    from app.schemas.common import JobStatus
    from app.schemas.video import VideoShortCreateRequest, VideoStatusResponse
    from app.services.video import veo_service
    from app.workers.tasks import video_tasks

    job_id = "expired-video-job"
    veo_service._JOBS[job_id] = VideoStatusResponse(
        job_id=job_id,
        status=JobStatus.queued,
        progress_pct=0,
    )
    veo_service._JOB_UPDATED_AT[job_id] = time.time() - veo_service.VIDEO_JOB_TTL_SECONDS - 1
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(video_tasks.generate_video_short_task, "apply_async", capture_enqueue)
    request = VideoShortCreateRequest.model_validate({
        "jobId": job_id,
        "prompt": "An expired video job id should enqueue again",
        "model": "fast",
        "task": "textToVideo",
        "aspectRatio": "9:16",
        "durationSeconds": 4,
    })

    response = asyncio.run(veo_service.enqueue_video_short_generation(request))

    assert response.status.value == "queued"
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "video-queue"
    assert job_id in veo_service._JOBS
    assert job_id in veo_service._JOB_UPDATED_AT


def test_image_duplicate_job_id_is_not_enqueued_twice(monkeypatch):
    import asyncio

    from app.api.v1 import image as image_api
    from app.schemas.image import ImageJobRequest

    job_id = "duplicate-image-job"
    image_api._IMAGE_JOB_IDS.pop(job_id, None)
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(image_api.generate_image_task, "apply_async", capture_enqueue)
    request = ImageJobRequest.model_validate({
        "jobId": job_id,
        "purpose": "promotion",
        "channels": ["instagram"],
        "image_prompt": "A single image should be generated",
        "n": 1,
    })

    async def enqueue_twice():
        first_response = await image_api.enqueue_image_job_endpoint(request)
        second_response = await image_api.enqueue_image_job_endpoint(request)
        return first_response, second_response

    first, second = asyncio.run(enqueue_twice())

    assert first.status == "queued"
    assert second.status == "queued"
    assert "이미 등록된 jobId" in second.message
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "image-queue"


def test_image_expired_job_id_can_be_enqueued_again(monkeypatch):
    import asyncio
    import time

    from app.api.v1 import image as image_api
    from app.schemas.image import ImageJobRequest

    job_id = "expired-image-job"
    image_api._IMAGE_JOB_IDS[job_id] = time.time() - image_api.IMAGE_JOB_ID_TTL_SECONDS - 1
    enqueued_requests = []

    def capture_enqueue(*, args, queue):
        enqueued_requests.append((args, queue))

    monkeypatch.setattr(image_api.generate_image_task, "apply_async", capture_enqueue)
    request = ImageJobRequest.model_validate({
        "jobId": job_id,
        "purpose": "promotion",
        "channels": ["instagram"],
        "image_prompt": "An expired image job id should enqueue again",
        "n": 1,
    })

    response = asyncio.run(image_api.enqueue_image_job_endpoint(request))

    assert response.status == "queued"
    assert len(enqueued_requests) == 1
    assert enqueued_requests[0][1] == "image-queue"
    assert job_id in image_api._IMAGE_JOB_IDS


def test_video_short_rejects_reference_images_mixed_with_image(client, auth_headers):
    response = client.post(
        "/v1/video/jobs",
        headers=auth_headers,
        json={
            "jobId": "test-short-invalid-1",
            "prompt": "Create a product short",
            "input": {
                "image": {
                    "gcsUri": "gs://bucket/start.png",
                    "mimeType": "image/png",
                },
                "referenceImages": [
                    {
                        "gcsUri": "gs://bucket/reference.png",
                        "mimeType": "image/png",
                    }
                ],
            },
        },
    )

    assert response.status_code == 422


def test_video_short_resolves_defaults_and_google_kwargs_exclude_external_fields():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.veo_service import _build_video_short_generate_kwargs, resolve_video_short_request

    class FakeTypes:
        class Image:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class VideoGenerationReferenceImage:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class GenerateVideosConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    create_request = VideoShortCreateRequest(
        jobId="test-short-job-2",
        model="fast",
        prompt="A product short",
        aspectRatio="9:16",
        durationSeconds=8,
        input={
            "image": {"gcsUri": "gs://bucket/start.png", "mimeType": "image/png"},
            "lastFrame": {"gcsUri": "gs://bucket/end.png", "mimeType": "image/png"},
        },
        platform="tiktok",
        metadata={"campaignId": "campaign-1"},
    )
    request = resolve_video_short_request(create_request)

    kwargs = _build_video_short_generate_kwargs(request, FakeTypes)
    config = kwargs["config"].kwargs

    assert kwargs["model"] == "veo-3.1-fast-generate-001"
    assert kwargs["image"].kwargs["gcs_uri"] == "gs://bucket/start.png"
    assert config["last_frame"].kwargs["gcs_uri"] == "gs://bucket/end.png"
    assert config["number_of_videos"] == 1
    assert config["resolution"] == "720p"
    assert "fps" not in config
    assert config["enhance_prompt"] is True
    assert "generate_audio" not in config
    assert config["compression_quality"] == "optimized"
    assert config["resize_mode"] == "crop"
    assert "metadata" not in config
    assert "platform" not in config
    assert "[GAIM 시각 콘텐츠 안전 정책]" in kwargs["prompt"]
    assert "비성적, 비폭력적, 비혐오적" in kwargs["prompt"]
    assert "[Visible writing policy]" in kwargs["prompt"]
    assert "render them only as short, common English words" in kwargs["prompt"]
    assert "Korean writing must not appear" in kwargs["prompt"]
    assert "8-second" not in kwargs["prompt"]
    assert "First and last frame direction:" in kwargs["prompt"]
    assert "provided image as the exact opening frame" in kwargs["prompt"]
    assert "provided lastFrame as the exact ending frame" in kwargs["prompt"]
    assert "scene description as the primary creative direction" in kwargs["prompt"]
    assert "A product short" in kwargs["prompt"]


def test_video_short_google_kwargs_include_generate_audio_only_when_false():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.veo_service import _build_video_short_generate_kwargs, resolve_video_short_request

    class FakeTypes:
        class GenerateVideosConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    create_request = VideoShortCreateRequest(
        jobId="test-short-audio-off",
        model="fast",
        prompt="A silent product short",
        aspectRatio="9:16",
        durationSeconds=4,
        task="textToVideo",
        advanced={"generateAudio": False},
    )
    request = resolve_video_short_request(create_request)

    kwargs = _build_video_short_generate_kwargs(request, FakeTypes)

    assert kwargs["config"].kwargs["generate_audio"] is False


def test_video_short_default_candidates_keep_veo_first_and_runway_fallback():
    from app.services.video.model_router import build_video_short_candidates

    fast_candidates = build_video_short_candidates("fast", "imageToVideo")
    assert [(item.provider, item.model) for item in fast_candidates] == [
        ("google", "veo-3.1-fast-generate-001"),
        ("runway", "gen4_turbo"),
    ]

    text_candidates = build_video_short_candidates("fast", "textToVideo")
    assert [(item.provider, item.model) for item in text_candidates] == [
        ("google", "veo-3.1-fast-generate-001"),
        ("runway", "gen4.5"),
    ]

    standard_candidates = build_video_short_candidates("standard")
    assert [(item.provider, item.model) for item in standard_candidates] == [
        ("google", "veo-3.1-generate-001"),
        ("runway", "gen4.5"),
    ]


def test_video_short_provider_override_selects_runway_only():
    from app.services.video.model_router import build_video_short_candidates

    candidates = build_video_short_candidates("standard", provider_override="runway")

    assert [(item.provider, item.model) for item in candidates] == [("runway", "gen4.5")]


def test_video_short_provider_override_selects_runway_model_by_task():
    from app.services.video.model_router import build_video_short_candidates

    text_candidates = build_video_short_candidates("fast", "textToVideo", provider_override="runway")
    image_candidates = build_video_short_candidates("fast", "imageToVideo", provider_override="runway")

    assert [(item.provider, item.model) for item in text_candidates] == [("runway", "gen4.5")]
    assert [(item.provider, item.model) for item in image_candidates] == [("runway", "gen4_turbo")]


def test_video_short_reference_to_video_uses_standard_model_and_eight_seconds():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.veo_service import resolve_video_short_request

    request = resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="reference-policy-job",
            prompt="레퍼런스 이미지를 참고한 숏폼",
            model="fast",
            platform="instagram_reels",
            task="referenceToVideo",
            aspectRatio="9:16",
            durationSeconds=4,
            input={
                "referenceImages": [
                    {
                        "bytesBase64Encoded": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=",
                        "mimeType": "image/png",
                    }
                ]
            },
        )
    )

    assert request.provider == "google"
    assert request.provider_model == "veo-3.1-generate-001"
    assert request.duration_seconds == 8


def test_video_short_generation_falls_back_to_runway_when_veo_fails(monkeypatch):
    from app.core.exceptions import ProviderError
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service

    def fail_google(request):
        raise ProviderError("forced veo failure")

    def succeed_runway(request, model):
        assert model == "gen4.5"
        return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"

    monkeypatch.setattr(veo_service, "_generate_video_short_sync", fail_google)
    monkeypatch.setattr(veo_service, "generate_runway_video_short_sync", succeed_runway)

    request = veo_service.resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="fallback-video-job",
            prompt="강릉 카페 홍보 영상",
            model="fast",
            platform="instagram_reels",
            task="textToVideo",
            aspectRatio="9:16",
            durationSeconds=8,
        )
    )

    video_bytes, provider, model_used, fallback_used, warnings = veo_service._generate_video_short_with_fallback_sync(
        request
    )

    assert video_bytes.startswith(b"\x00\x00\x00\x18ftyp")
    assert provider == "runway"
    assert model_used == "gen4.5"
    assert fallback_used is True
    assert "google/veo-3.1-fast-generate-001 failed" in warnings[0]


def test_video_short_retryable_primary_error_fails_without_celery_retry(monkeypatch):
    from app.core.exceptions import ProviderAuthenticationError, ProviderTimeoutError
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service

    def timeout_google(request):
        raise ProviderTimeoutError("Google provider request timed out.")

    def fail_runway_auth(request, model):
        raise ProviderAuthenticationError("Runway provider authentication failed.")

    monkeypatch.setattr(veo_service, "_generate_video_short_sync", timeout_google)
    monkeypatch.setattr(veo_service, "generate_runway_video_short_sync", fail_runway_auth)

    request = veo_service.resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="retry-video-job",
            prompt="강릉 카페 홍보 영상",
            model="fast",
            platform="instagram_reels",
            task="textToVideo",
            aspectRatio="9:16",
            durationSeconds=8,
        )
    )

    try:
        veo_service._generate_video_short_with_fallback_sync(request)
    except ProviderAuthenticationError:
        pass
    else:
        raise AssertionError("Expected final fallback auth failure when Celery retry is disabled")


def test_video_short_retryable_primary_error_survives_fallback_auth_failure_when_retry_enabled(monkeypatch):
    from app.config import get_settings
    from app.core.exceptions import ProviderAuthenticationError, ProviderTimeoutError
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video import veo_service

    def timeout_google(request):
        raise ProviderTimeoutError("Google provider request timed out.")

    def fail_runway_auth(request, model):
        raise ProviderAuthenticationError("Runway provider authentication failed.")

    monkeypatch.setenv("CELERY_TASK_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(veo_service, "_generate_video_short_sync", timeout_google)
    monkeypatch.setattr(veo_service, "generate_runway_video_short_sync", fail_runway_auth)

    request = veo_service.resolve_video_short_request(
        VideoShortCreateRequest(
            jobId="retry-video-job",
            prompt="강릉 카페 홍보 영상",
            model="fast",
            platform="instagram_reels",
            task="textToVideo",
            aspectRatio="9:16",
            durationSeconds=8,
        )
    )

    try:
        veo_service._generate_video_short_with_fallback_sync(request)
    except ProviderTimeoutError:
        pass
    else:
        raise AssertionError("Expected retryable Google timeout to survive fallback auth failure")


def test_video_completed_callback_includes_provider_metadata(monkeypatch):
    from app.services import callbacks

    captured = {}

    async def fake_post_callback(path, payload):
        captured["path"] = path
        captured["payload"] = payload

    monkeypatch.setattr(callbacks, "_post_callback", fake_post_callback)

    import asyncio

    asyncio.run(
        callbacks.notify_job_completed(
            job_id="video-callback-metadata",
            result_url="http://localhost:8000/generated/videos/result.mp4",
            duration_ms=1234,
            provider="google",
            model_used="veo-3.1-fast-generate-001",
            fallback_used=False,
            warnings=[],
        )
    )

    assert captured["path"] == "/internal/callback/jobs/video-callback-metadata"
    assert captured["payload"]["status"] == "completed"
    assert captured["payload"]["provider"] == "google"
    assert captured["payload"]["modelUsed"] == "veo-3.1-fast-generate-001"
    assert captured["payload"]["fallbackUsed"] is False
    assert captured["payload"]["warnings"] == []


def test_runway_payload_preserves_supported_video_duration():
    from app.schemas.video import VideoShortCreateRequest
    from app.services.video.runway_service import _build_runway_payload
    from app.services.video.veo_service import resolve_video_short_request

    for duration in (4, 6, 8):
        request = resolve_video_short_request(
            VideoShortCreateRequest(
                jobId=f"runway-duration-{duration}",
                prompt="강릉 카페 홍보 영상",
                model="fast",
                providerOverride="runway",
                platform="instagram_reels",
                task="textToVideo",
                aspectRatio="9:16",
                durationSeconds=duration,
            )
        )

        payload = _build_runway_payload(request, "gen4.5")

        assert payload["duration"] == duration


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


def test_google_vertex_auth_requires_service_account(monkeypatch):
    from app.config import Settings
    from app.services.image.google_service import _build_google_client
    from app.core.exceptions import ProviderError

    settings = Settings(google_auth_mode="vertex_ai", gcp_service_account_json="{}")
    try:
        _build_google_client(settings)
    except ProviderError as exc:
        assert "Google provider authentication failed" in str(exc)
        assert "GCP_SERVICE_ACCOUNT_JSON" not in str(exc)
    else:
        raise AssertionError("Expected ProviderError")


def test_production_settings_reject_eager_mode(monkeypatch):
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "production-secret")
    monkeypatch.setenv("WAS_INTERNAL_TOKEN", "production-token")
    monkeypatch.setenv("WAS_BASE_URL", "https://was.example.com")
    monkeypatch.setenv("AI_PROVIDER_MODE", "mock")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "CELERY_TASK_ALWAYS_EAGER must be false in production" in str(exc_info.value)


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


def test_video_extract_generated_video_bytes_rejects_empty_response():
    from types import SimpleNamespace

    from app.services.video.veo_service import _extract_generated_video_bytes

    operation = SimpleNamespace(error=None, response=SimpleNamespace(generated_videos=[]), result=None)

    try:
        _extract_generated_video_bytes(operation, "Veo")
    except RuntimeError as exc:
        assert "did not include generated videos" in str(exc)
    else:
        raise AssertionError("Expected empty generated videos to fail")


def test_video_operation_done_none_is_treated_as_pending():
    from types import SimpleNamespace

    from app.services.video.veo_service import _is_operation_done

    assert _is_operation_done(SimpleNamespace(done=None), "Veo") is False


def test_video_extract_generated_video_bytes_rejects_missing_video_data():
    from types import SimpleNamespace

    from app.services.video.veo_service import _extract_generated_video_bytes

    operation = SimpleNamespace(
        error=None,
        response=SimpleNamespace(generated_videos=[SimpleNamespace(video=None)]),
        result=None,
    )

    try:
        _extract_generated_video_bytes(operation, "Video short")
    except RuntimeError as exc:
        assert "did not include video data" in str(exc)
    else:
        raise AssertionError("Expected missing video data to fail")


def test_video_to_google_image_rejects_invalid_base64():
    from types import SimpleNamespace

    from app.core.exceptions import RequestValidationError
    from app.schemas.video import VideoShortMediaInput
    from app.services.video.veo_service import _to_google_image

    media = VideoShortMediaInput(bytesBase64Encoded="not-valid-base64", mimeType="image/png")
    fake_types = SimpleNamespace(Image=lambda **kwargs: kwargs)

    try:
        _to_google_image(media, fake_types)
    except RequestValidationError as exc:
        assert "not valid base64" in exc.message
    else:
        raise AssertionError("Expected invalid base64 media to fail")


def test_provider_error_classification_marks_rate_limit_retryable():
    from app.core.exceptions import ProviderRateLimitError
    from app.core.provider_errors import classify_openai_exception

    class FakeRateLimitError(Exception):
        status_code = 429

    classified = classify_openai_exception(FakeRateLimitError("api key sk-secret leaked detail"))

    assert isinstance(classified, ProviderRateLimitError)
    assert classified.retryable is True
    assert "sk-secret" not in classified.message


def test_image_create_warning_does_not_expose_raw_exception(monkeypatch):
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def fail_google(request):
        raise RuntimeError("raw provider detail token=secret-value")

    monkeypatch.setattr(create_service, "generate_google_images", fail_google)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    import asyncio

    result = asyncio.run(create_service.create_image(request))
    warnings_text = "\n".join(result.routing.warnings)

    assert "secret-value" not in warnings_text
    assert "raw provider detail" not in warnings_text
    assert "unexpected provider failure" in warnings_text


def test_image_create_auth_error_does_not_fallback(monkeypatch):
    import asyncio

    from app.core.exceptions import ProviderAuthenticationError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def fail_google_auth(request):
        raise ProviderAuthenticationError("Google provider authentication failed.")

    async def unexpected_openai_call(request):
        raise AssertionError("OpenAI fallback should not run after provider auth failure")

    monkeypatch.setattr(create_service, "generate_google_images", fail_google_auth)
    monkeypatch.setattr(create_service, "generate_openai_images", unexpected_openai_call)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    try:
        asyncio.run(create_service.create_image(request))
    except ProviderAuthenticationError:
        pass
    else:
        raise AssertionError("Expected provider authentication failure to bypass fallback")


def test_image_create_all_retryable_failures_use_placeholder_when_celery_retry_disabled(monkeypatch):
    import asyncio

    from app.core.exceptions import ProviderTimeoutError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def timeout_provider(request):
        raise ProviderTimeoutError("provider timed out")

    monkeypatch.setattr(create_service, "generate_google_images", timeout_provider)
    monkeypatch.setattr(create_service, "generate_openai_images", timeout_provider)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    result = asyncio.run(create_service.create_image(request))

    assert result.provider == "local"
    assert result.routing.fallback_used is True


def test_image_create_all_retryable_failures_are_retried_when_retry_enabled(monkeypatch):
    import asyncio

    from app.config import get_settings
    from app.core.exceptions import ProviderTimeoutError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def timeout_provider(request):
        raise ProviderTimeoutError("provider timed out")

    monkeypatch.setenv("CELERY_TASK_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(create_service, "generate_google_images", timeout_provider)
    monkeypatch.setattr(create_service, "generate_openai_images", timeout_provider)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    try:
        asyncio.run(create_service.create_image(request))
    except ProviderTimeoutError:
        pass
    else:
        raise AssertionError("Expected retryable provider failure instead of local placeholder")


def test_image_create_mixed_retryable_and_non_retryable_uses_placeholder_when_retry_enabled(monkeypatch):
    import asyncio

    from app.config import get_settings
    from app.core.exceptions import ProviderRequestError, ProviderTimeoutError
    from app.schemas.image import ImageRequest
    from app.services.image import create_service

    async def timeout_google(request):
        raise ProviderTimeoutError("provider timed out")

    async def reject_openai(request):
        raise ProviderRequestError("provider rejected request")

    monkeypatch.setenv("CELERY_TASK_RETRY_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(create_service, "generate_google_images", timeout_google)
    monkeypatch.setattr(create_service, "generate_openai_images", reject_openai)

    request = ImageRequest(
        purpose="홍보",
        channels=["인스타"],
        image_prompt="카페 이미지",
        visual_mood="bright",
        n=1,
    )

    result = asyncio.run(create_service.create_image(request))

    assert result.provider == "local"
    assert result.routing.fallback_used is True


def test_image_job_failure_callback_uses_public_error(monkeypatch):
    from app.workers.tasks import image_tasks

    async def fail_create_image(request):
        raise RuntimeError("provider payload contained secret-value")

    captured = {}

    async def fake_progress(job_id, progress):
        return None

    async def fake_failed(job_id, error_message, duration_ms=None):
        captured["job_id"] = job_id
        captured["error"] = error_message

    monkeypatch.setattr(image_tasks, "create_image", fail_create_image)
    monkeypatch.setattr(image_tasks, "notify_job_progress", fake_progress)
    monkeypatch.setattr(image_tasks, "notify_job_failed", fake_failed)

    import asyncio

    result = asyncio.run(
        image_tasks._run_image_job(
            {
                "jobId": "job-safe-error",
                "purpose": "홍보",
                "channels": ["인스타"],
                "image_prompt": "카페 이미지",
                "visual_mood": "bright",
                "n": 1,
            }
        )
    )

    assert result["status"] == "failed"
    assert "secret-value" not in result["error"]
    assert "secret-value" not in captured["error"]
    assert captured["job_id"] == "job-safe-error"


def test_video_job_public_error_message_does_not_expose_raw_exception():
    from app.core.provider_errors import classify_google_exception, public_job_error_message

    error = public_job_error_message(classify_google_exception(RuntimeError("uri=https://internal.example/secret")))

    assert "internal.example" not in error
    assert "secret" not in error
    assert "오류" in error or "외부 AI 서비스" in error


def test_retryable_provider_error_is_not_retried_by_default(monkeypatch):
    from types import SimpleNamespace

    from app.core.exceptions import ProviderTimeoutError, RequestValidationError
    from app.workers.tasks import image_tasks

    task = SimpleNamespace(request=SimpleNamespace(retries=0), max_retries=2)
    exhausted_task = SimpleNamespace(request=SimpleNamespace(retries=2), max_retries=2)

    assert image_tasks._should_retry(task, ProviderTimeoutError("timeout")) is False
    assert image_tasks._should_retry(exhausted_task, ProviderTimeoutError("timeout")) is False
    assert image_tasks._should_retry(task, RequestValidationError("bad request")) is False


def test_retryable_provider_error_is_marked_for_celery_retry_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from app.config import get_settings
    from app.core.exceptions import ProviderTimeoutError, RequestValidationError
    from app.workers.tasks import image_tasks

    monkeypatch.setenv("CELERY_TASK_RETRY_ENABLED", "true")
    get_settings.cache_clear()

    task = SimpleNamespace(request=SimpleNamespace(retries=0), max_retries=2)
    exhausted_task = SimpleNamespace(request=SimpleNamespace(retries=2), max_retries=2)

    assert image_tasks._should_retry(task, ProviderTimeoutError("timeout")) is True
    assert image_tasks._should_retry(exhausted_task, ProviderTimeoutError("timeout")) is False
    assert image_tasks._should_retry(task, RequestValidationError("bad request")) is False


def test_celery_delivery_settings_are_configured():
    from app.workers.celery_app import celery_app

    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.task_acks_on_failure_or_timeout is True


def test_provider_time_limits_are_aligned_with_celery_limits():
    from app.config import get_settings

    settings = get_settings()

    assert settings.video_max_wait_sec < settings.celery_task_soft_time_limit
    assert settings.celery_task_soft_time_limit < settings.celery_task_time_limit
    assert settings.celery_task_time_limit < settings.celery_broker_visibility_timeout


def test_google_client_uses_configured_timeout(monkeypatch):
    from app.config import get_settings
    from app.services.image.google_service import _build_google_client

    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("GOOGLE_PROVIDER_TIMEOUT_MS", "12345")
    get_settings.cache_clear()

    client = _build_google_client(get_settings(), "gemini-2.5-flash-image")

    assert client._api_client._http_options.timeout == 12345


def test_openai_image_client_uses_configured_timeout_and_closes(monkeypatch):
    import asyncio
    import sys
    from types import SimpleNamespace

    from app.config import get_settings
    from app.schemas.image import ProviderImageRequest
    from app.services.image.openai_service import generate_openai_images

    captured = {"timeout": None, "closed": False}

    class FakeImages:
        async def generate(self, **kwargs):
            return SimpleNamespace(data=[
                SimpleNamespace(b64_json="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax7Z3sAAAAASUVORK5CYII=")
            ])

    class FakeAsyncOpenAI:
        def __init__(self, api_key, timeout):
            captured["timeout"] = timeout
            self.images = FakeImages()

        async def close(self):
            captured["closed"] = True

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    monkeypatch.setenv("AI_PROVIDER_MODE", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_PROVIDER_TIMEOUT_SEC", "12.5")
    get_settings.cache_clear()

    result = asyncio.run(generate_openai_images(ProviderImageRequest(
        prompt="timeout test",
        model="gpt-image-1.5",
        n=1,
    )))

    assert result.provider == "openai"
    assert captured["timeout"] == 12.5
    assert captured["closed"] is True


def test_reference_image_download_uses_configured_timeout(monkeypatch):
    from io import BytesIO

    from app.config import get_settings
    from app.services.image import references

    captured = {"timeout": None}

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url, timeout):
        captured["timeout"] = timeout
        return FakeResponse(b"image-bytes")

    monkeypatch.setattr(references, "urlopen", fake_urlopen)
    monkeypatch.setenv("REFERENCE_IMAGE_DOWNLOAD_TIMEOUT_SEC", "7.5")
    get_settings.cache_clear()

    payload = references._load_from_url("https://example.com/reference.png")

    assert payload == b"image-bytes"
    assert captured["timeout"] == 7.5


def test_runway_requests_use_configured_timeouts(monkeypatch):
    from io import BytesIO

    from app.config import get_settings
    from app.services.video import runway_service

    captured = {"request_timeout": None, "download_timeout": None}

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(target, timeout):
        if hasattr(target, "full_url"):
            captured["request_timeout"] = timeout
            return FakeResponse(b'{"id":"task-1"}')
        captured["download_timeout"] = timeout
        return FakeResponse(b"video-bytes")

    monkeypatch.setattr(runway_service.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("RUNWAY_REQUEST_TIMEOUT_SEC", "8.5")
    monkeypatch.setenv("RUNWAY_DOWNLOAD_TIMEOUT_SEC", "9.5")
    get_settings.cache_clear()

    settings = get_settings()
    response = runway_service._runway_json_request("POST", "https://runway.test/task", {}, settings)
    video_bytes = runway_service._download_runway_output("https://runway.test/output.mp4")

    assert response == {"id": "task-1"}
    assert video_bytes == b"video-bytes"
    assert captured["request_timeout"] == 8.5
    assert captured["download_timeout"] == 9.5


def test_worker_job_lock_duplicate_skips_run(monkeypatch):
    from app.workers import job_locks

    called = {"run": False}

    def fail_if_called():
        called["run"] = True
        return {"status": "ran"}

    monkeypatch.setattr(job_locks, "acquire_job_lock", lambda job_id, job_type: None)

    result = job_locks.run_with_job_lock(
        job_id="duplicate-job",
        job_type="image",
        on_duplicate=lambda: {"status": "duplicate_skipped"},
        run=fail_if_called,
    )

    assert result == {"status": "duplicate_skipped"}
    assert called["run"] is False


def test_video_task_result_does_not_include_request_payload(monkeypatch):
    from app.workers.tasks import video_tasks

    async def fake_generation(job_id, request):
        return {
            "jobId": job_id,
            "status": "completed",
            "videoUrl": "http://testserver/generated/videos/result.mp4",
            "callbacks": {},
        }

    monkeypatch.setattr(video_tasks, "_run_live_video_generation", fake_generation)

    result = video_tasks._run_video_generation(
        {
            "jobId": "video-result-payload",
            "prompt": "A small video",
            "model": "fast",
            "durationSeconds": 4,
            "aspectRatio": "16:9",
            "metadata": {"largeInput": "x" * 1000},
        }
    )

    assert result["status"] == "completed"
    assert "request" not in result


def test_image_reference_base64_rejects_oversized_input(monkeypatch):
    import base64

    from app.config import get_settings
    from app.core.exceptions import RequestValidationError
    from app.schemas.image import ReferenceImage
    from app.services.image.references import load_reference_image_bytes

    monkeypatch.setenv("MAX_IMAGE_REFERENCE_BYTES", "4")
    get_settings.cache_clear()

    reference = ReferenceImage(
        b64_json=base64.b64encode(b"12345").decode("ascii"),
        mime_type="image/png",
    )

    try:
        load_reference_image_bytes(reference)
    except RequestValidationError as exc:
        assert "Image reference exceeds" in exc.message
    else:
        raise AssertionError("Expected oversized image reference to fail")


def test_image_reference_local_url_rejects_oversized_file(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.core.exceptions import RequestValidationError
    from app.schemas.image import ReferenceImage
    from app.services.image.references import load_reference_image_bytes

    image_path = tmp_path / "storage" / "images" / "large.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"12345")
    monkeypatch.setenv("STORAGE_BASE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("STORAGE_PUBLIC_BASE_URL", "http://testserver/generated")
    monkeypatch.setenv("MAX_IMAGE_REFERENCE_BYTES", "4")
    get_settings.cache_clear()

    reference = ReferenceImage(
        image_url="http://testserver/generated/images/large.png",
        mime_type="image/png",
    )

    try:
        load_reference_image_bytes(reference)
    except RequestValidationError as exc:
        assert "Image reference exceeds" in exc.message
    else:
        raise AssertionError("Expected oversized local image reference to fail")


def test_video_input_image_base64_rejects_oversized_input(monkeypatch):
    import base64
    from types import SimpleNamespace

    from app.config import get_settings
    from app.core.exceptions import RequestValidationError
    from app.schemas.video import VideoShortMediaInput
    from app.services.video.veo_service import _to_google_image

    monkeypatch.setenv("MAX_VIDEO_INPUT_IMAGE_BYTES", "4")
    get_settings.cache_clear()
    media = VideoShortMediaInput(
        bytesBase64Encoded=base64.b64encode(b"12345").decode("ascii"),
        mimeType="image/png",
    )
    fake_types = SimpleNamespace(Image=lambda **kwargs: kwargs)

    try:
        _to_google_image(media, fake_types)
    except RequestValidationError as exc:
        assert "Video input image exceeds" in exc.message
    else:
        raise AssertionError("Expected oversized video input image to fail")


def test_local_storage_cleanup_dry_run_keeps_files(tmp_path):
    import os
    import time

    from app.storage.local_cleanup import cleanup_local_storage

    old_file = tmp_path / "images" / "old.png"
    recent_file = tmp_path / "videos" / "recent.mp4"
    old_file.parent.mkdir(parents=True)
    recent_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    recent_file.write_bytes(b"recent")
    now = time.time()
    os.utime(old_file, (now - 10_000, now - 10_000))
    os.utime(recent_file, (now, now))

    result = cleanup_local_storage(
        base_dir=tmp_path,
        retention_seconds=3600,
        dry_run=True,
        now=now,
    )

    assert result.scanned_files == 2
    assert result.delete_candidates == 1
    assert result.deleted_files == 0
    assert old_file.exists()
    assert recent_file.exists()


def test_local_storage_cleanup_deletes_old_files_and_empty_dirs(tmp_path):
    import os
    import time

    from app.storage.local_cleanup import cleanup_local_storage

    old_file = tmp_path / "images" / "nested" / "old.png"
    recent_file = tmp_path / "videos" / "recent.mp4"
    ignored_file = tmp_path / "manual.txt"
    old_file.parent.mkdir(parents=True)
    recent_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    recent_file.write_bytes(b"recent")
    ignored_file.write_bytes(b"ignored")
    now = time.time()
    os.utime(old_file, (now - 10_000, now - 10_000))
    os.utime(recent_file, (now, now))
    os.utime(ignored_file, (now - 10_000, now - 10_000))

    result = cleanup_local_storage(
        base_dir=tmp_path,
        retention_seconds=3600,
        dry_run=False,
        now=now,
    )

    assert result.scanned_files == 2
    assert result.delete_candidates == 1
    assert result.deleted_files == 1
    assert result.deleted_bytes == 3
    assert result.removed_empty_dirs >= 1
    assert not old_file.exists()
    assert not old_file.parent.exists()
    assert recent_file.exists()
    assert ignored_file.exists()


def test_async_stack_smoke_active_queue_names():
    from tools.integration_async_stack_smoke import active_queue_names

    queues = active_queue_names({
        "worker-1": [{"name": "image-queue"}, {"name": "celery"}],
        "worker-2": [{"name": "video-queue"}],
    })

    assert queues == {"image-queue", "video-queue", "celery"}


def test_async_stack_smoke_result_payload_rejects_request_key():
    from tools.integration_async_stack_smoke import validate_result_payload

    check = validate_result_payload(
        "video_short_job",
        state="SUCCESS",
        payload={"status": "failed", "request": {"bytesBase64Encoded": "large"}},
        expected_status="failed",
        disallow_keys={"request"},
    )

    assert check.status == "fail"
    assert "forbidden keys" in check.detail


def test_async_stack_smoke_result_payload_accepts_expected_status():
    from tools.integration_async_stack_smoke import validate_result_payload

    check = validate_result_payload(
        "image_job",
        state="SUCCESS",
        payload={"status": "completed", "images": ["http://testserver/generated/images/result.png"]},
        expected_status="completed",
        disallow_keys=set(),
    )

    assert check.status == "ok"


def test_async_stack_smoke_skipped_status_is_not_failure():
    from tools.integration_async_stack_smoke import SmokeCheck, has_failure

    checks = [
        SmokeCheck("redis", "ok"),
        SmokeCheck("redis_appendonly", "warn"),
        SmokeCheck("provider_jobs", "skipped"),
    ]

    assert has_failure(checks) is False


def test_async_stack_smoke_positive_int_helper():
    from tools.integration_async_stack_smoke import _positive_int

    assert _positive_int("536870912") is True
    assert _positive_int("0") is False
    assert _positive_int("512mb") is False


def test_async_stack_smoke_reads_dotenv_value(monkeypatch, tmp_path):
    import tools.integration_async_stack_smoke as smoke

    env_file = tmp_path / ".env"
    env_file.write_text('AI_PROVIDER_MODE="mock"\nREDIS_REQUIREPASS=secret\n', encoding="utf-8")
    monkeypatch.setattr(smoke, "ENV_FILE", env_file)

    assert smoke.read_dotenv_value("AI_PROVIDER_MODE") == "mock"
    assert smoke.read_dotenv_value("MISSING") is None


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


def test_video_generate_and_status(client, auth_headers):
    response = client.post(
        "/v1/video/provider-generate",
        headers=auth_headers,
        json={"jobId": "test-video-job-1", "prompt": "강릉 카페 홍보 영상", "duration_seconds": 8},
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    assert job_id == "test-video-job-1"

    status = client.get(f"/v1/video/status/{job_id}", headers=auth_headers)
    assert status.status_code == 200
    data = status.json()
    assert data["status"] == "failed"
    assert data["videoUrl"] is None
    assert "Mock video generation does not create playable MP4" in data["error"]


def test_video_duration_3_is_normalized_to_4(client, auth_headers):
    response = client.post(
        "/v1/video/provider-generate",
        headers=auth_headers,
        json={
            "jobId": "test-video-job-2",
            "model": "veo-3.1-fast-generate-001",
            "prompt": "신선한 생선이 생선 가게 앞에서 한마리씩 튀어오르는 영상을 만들어줘",
            "duration_seconds": 3,
            "aspect_ratio": "16:9",
        },
    )
    assert response.status_code == 200
    assert "duration_seconds=4" in response.json()["message"]


def test_video_provider_rejects_deprecated_veo_3_0(client, auth_headers):
    response = client.post(
        "/v1/video/provider-generate",
        headers=auth_headers,
        json={
            "jobId": "test-video-job-deprecated",
            "model": "veo-3.0-fast-generate-001",
            "prompt": "강릉 카페 홍보 영상",
            "duration_seconds": 4,
            "aspect_ratio": "16:9",
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "REQUEST_VALIDATION_ERROR"
    assert "Veo 3.0 was shut down on 2026-06-30" in data["message"]
