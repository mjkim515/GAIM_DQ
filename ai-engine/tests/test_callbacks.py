import asyncio
from urllib import error


def test_post_callback_retries_then_succeeds(monkeypatch):
    from app.services import callbacks

    attempts = []
    sleeps = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b""

    def fake_urlopen(callback_request, timeout):
        attempts.append((callback_request.full_url, timeout))
        if len(attempts) < 3:
            raise error.URLError("temporary outage")
        return FakeResponse()

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(callbacks.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(callbacks.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(callbacks.random, "uniform", lambda start, end: 0.0)

    result = asyncio.run(callbacks._post_callback("/internal/callback/jobs/job-1", {"status": "completed"}))

    assert result is True
    assert len(attempts) == 3
    assert [attempt[1] for attempt in attempts] == [5.0, 5.0, 5.0]
    assert sleeps == [0.5, 1.0]


def test_post_callback_returns_false_after_all_attempts(monkeypatch):
    from app.services import callbacks

    attempts = []
    sleeps = []

    def fake_urlopen(callback_request, timeout):
        attempts.append(callback_request.full_url)
        raise error.URLError("still down")

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(callbacks.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(callbacks.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(callbacks.random, "uniform", lambda start, end: 0.0)

    result = asyncio.run(callbacks._post_callback("/internal/callback/jobs/job-2", {"status": "failed"}))

    assert result is False
    assert len(attempts) == 4
    assert sleeps == [0.5, 1.0, 2.0]


def test_callback_retry_delay_uses_exponential_backoff_with_jitter(monkeypatch):
    from app.services import callbacks

    monkeypatch.setattr(callbacks.random, "uniform", lambda start, end: 0.25)

    assert callbacks._callback_retry_delay(1) == 0.75
    assert callbacks._callback_retry_delay(2) == 1.25
    assert callbacks._callback_retry_delay(3) == 2.25
    assert callbacks._callback_retry_delay(6) == 8.25


def test_notify_job_progress_attempts_once(monkeypatch):
    from app.services import callbacks

    attempts = []

    def fake_urlopen(callback_request, timeout):
        attempts.append(callback_request.full_url)
        raise error.URLError("progress endpoint unavailable")

    async def fail_if_sleep_called(delay):
        raise AssertionError("progress callback should not retry")

    monkeypatch.setattr(callbacks.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(callbacks.asyncio, "sleep", fail_if_sleep_called)

    result = asyncio.run(callbacks.notify_job_progress("progress-job", 5))

    assert result is False
    assert attempts == ["http://localhost:8080/internal/callback/jobs/progress-job/progress"]
