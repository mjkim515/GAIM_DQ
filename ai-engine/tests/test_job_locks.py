from redis.exceptions import RedisError
import pytest


@pytest.fixture(autouse=True)
def enable_job_lock(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("CELERY_JOB_LOCK_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_acquire_job_lock_uses_task_id_as_token(monkeypatch):
    from app.workers import job_locks

    stored = {}

    class FakeRedis:
        def set(self, key, value, nx, ex):
            stored["key"] = key
            stored["value"] = value
            stored["nx"] = nx
            stored["ex"] = ex
            return True

        def close(self):
            stored["closed"] = True

    monkeypatch.setattr(job_locks.Redis, "from_url", lambda *args, **kwargs: FakeRedis())

    lock = job_locks.acquire_job_lock("job-1", "image", task_id="task-1")

    assert isinstance(lock, job_locks.JobLock)
    assert lock.token == "task-1"
    assert stored["key"] == "gaim:ai-engine:job-lock:image:job-1"
    assert stored["value"] == "task-1"
    assert stored["nx"] is True
    assert stored["ex"] == 900


def test_acquire_job_lock_reenters_same_task_id_and_refreshes_ttl(monkeypatch):
    from app.workers import job_locks

    calls = []

    class FakeRedis:
        def set(self, key, value, nx, ex):
            calls.append(("set", key, value, nx, ex))
            return False

        def get(self, key):
            calls.append(("get", key))
            return "task-1"

        def expire(self, key, ex):
            calls.append(("expire", key, ex))

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(job_locks.Redis, "from_url", lambda *args, **kwargs: FakeRedis())

    lock = job_locks.acquire_job_lock("job-1", "video", task_id="task-1")

    assert isinstance(lock, job_locks.JobLock)
    assert lock.token == "task-1"
    assert ("expire", "gaim:ai-engine:job-lock:video:job-1", 900) in calls
    assert ("close",) not in calls


def test_acquire_job_lock_rejects_different_task_id(monkeypatch):
    from app.workers import job_locks

    calls = []

    class FakeRedis:
        def set(self, key, value, nx, ex):
            return False

        def get(self, key):
            return "other-task"

        def close(self):
            calls.append("close")

    monkeypatch.setattr(job_locks.Redis, "from_url", lambda *args, **kwargs: FakeRedis())

    lock = job_locks.acquire_job_lock("job-1", "video", task_id="task-1")

    assert lock is None
    assert calls == ["close"]


def test_run_with_job_lock_passes_task_id(monkeypatch):
    from app.workers import job_locks

    captured = {}

    def fake_acquire_job_lock(job_id, job_type, task_id=None):
        captured["job_id"] = job_id
        captured["job_type"] = job_type
        captured["task_id"] = task_id
        return False

    monkeypatch.setattr(job_locks, "acquire_job_lock", fake_acquire_job_lock)

    result = job_locks.run_with_job_lock(
        job_id="job-1",
        job_type="image",
        task_id="task-1",
        on_duplicate=lambda: {"status": "duplicate_skipped"},
        run=lambda: {"status": "ran"},
    )

    assert result == {"status": "ran"}
    assert captured == {"job_id": "job-1", "job_type": "image", "task_id": "task-1"}


def test_acquire_job_lock_runs_without_lock_when_redis_unavailable(monkeypatch):
    from app.workers import job_locks

    class FakeRedis:
        def set(self, key, value, nx, ex):
            raise RedisError("redis unavailable")

        def close(self):
            pass

    monkeypatch.setattr(job_locks.Redis, "from_url", lambda *args, **kwargs: FakeRedis())

    assert job_locks.acquire_job_lock("job-1", "image", task_id="task-1") is False
