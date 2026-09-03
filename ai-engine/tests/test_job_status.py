import json


def test_record_terminal_status_and_get_terminal_status(monkeypatch):
    from app.services import job_status

    stored = {}

    class FakeRedis:
        def set(self, key, value, ex):
            stored[key] = {"value": value, "ex": ex}

        def get(self, key):
            return stored[key]["value"]

        def close(self):
            stored["closed"] = True

    monkeypatch.setattr(job_status.Redis, "from_url", lambda *args, **kwargs: FakeRedis())

    job_status.record_terminal_status(
        "image",
        "terminal-image-job",
        {
            "status": "completed",
            "images": ["http://testserver/generated/images/result.png"],
            "progressPct": 100,
        },
    )

    key = "gaim:ai-engine:job-terminal:image:terminal-image-job"
    assert stored[key]["ex"] == 24 * 60 * 60
    assert json.loads(stored[key]["value"])["status"] == "completed"
    assert job_status.get_terminal_status("image", "terminal-image-job") == {
        "status": "completed",
        "images": ["http://testserver/generated/images/result.png"],
        "progressPct": 100,
    }


def test_celery_result_payload_prefers_terminal_status(monkeypatch):
    from app.services import job_status

    monkeypatch.setattr(job_status, "get_terminal_status", lambda job_type, job_id: {
        "status": "completed",
        "images": ["http://testserver/generated/images/result.png"],
        "progressPct": 100,
    })
    monkeypatch.setattr(
        job_status,
        "get_remembered_task_id",
        lambda job_type, job_id: (_ for _ in ()).throw(AssertionError("Celery lookup should not run")),
    )

    result = job_status.celery_result_payload_for_job("image", "terminal-image-job")

    assert result == {
        "jobId": "terminal-image-job",
        "status": "completed",
        "images": ["http://testserver/generated/images/result.png"],
        "progressPct": 100,
    }


def test_celery_pending_with_task_mapping_returns_processing(monkeypatch):
    from app.services import job_status

    class FakeAsyncResult:
        state = "PENDING"

        def __init__(self, task_id, app):
            self.task_id = task_id
            self.app = app

    monkeypatch.setattr(job_status, "get_terminal_status", lambda job_type, job_id: None)
    monkeypatch.setattr(job_status, "get_remembered_task_id", lambda job_type, job_id: "task-1")
    monkeypatch.setattr(job_status, "AsyncResult", FakeAsyncResult)

    result = job_status.celery_result_payload_for_job("video", "pending-video-job")

    assert result == {
        "jobId": "pending-video-job",
        "status": "processing",
        "progressPct": 5,
    }


def test_celery_result_payload_without_terminal_or_mapping_returns_none(monkeypatch):
    from app.services import job_status

    monkeypatch.setattr(job_status, "get_terminal_status", lambda job_type, job_id: None)
    monkeypatch.setattr(job_status, "get_remembered_task_id", lambda job_type, job_id: None)

    assert job_status.celery_result_payload_for_job("image", "missing-image-job") is None


def test_image_status_without_terminal_or_mapping_returns_unknown_job(client, auth_headers, monkeypatch):
    from app.api.v1 import image as image_api

    monkeypatch.setattr(image_api, "celery_result_payload_for_job", lambda job_type, job_id: None)

    response = client.get("/v1/image/status/missing-image-job", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "Unknown job_id"


def test_record_terminal_status_does_not_raise_on_redis_error(monkeypatch):
    from app.services import job_status

    def raise_redis_error(*args, **kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(job_status.Redis, "from_url", raise_redis_error)

    job_status.record_terminal_status("video", "terminal-video-job", {"status": "failed"})
