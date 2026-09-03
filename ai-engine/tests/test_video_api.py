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
