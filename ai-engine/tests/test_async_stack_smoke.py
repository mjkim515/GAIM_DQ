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
