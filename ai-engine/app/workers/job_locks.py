import logging
import uuid
from dataclasses import dataclass
from typing import Callable, TypeVar

from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class JobLock:
    key: str
    token: str
    client: Redis


def run_with_job_lock(
    *,
    job_id: str | None,
    job_type: str,
    on_duplicate: Callable[[], T],
    run: Callable[[], T],
) -> T:
    lock = acquire_job_lock(job_id=job_id, job_type=job_type)
    if lock is None and job_id:
        logger.info("Duplicate %s job skipped job_id=%s", job_type, job_id)
        return on_duplicate()
    if lock is False:
        return run()

    try:
        return run()
    finally:
        release_job_lock(lock)


def acquire_job_lock(job_id: str | None, job_type: str) -> JobLock | bool | None:
    settings = get_settings()
    if not settings.celery_job_lock_enabled or not job_id:
        return False

    key = f"gaim:ai-engine:job-lock:{job_type}:{job_id}"
    token = uuid.uuid4().hex
    client: Redis | None = None
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        acquired = client.set(key, token, nx=True, ex=settings.celery_job_lock_ttl)
    except RedisError as exc:
        if client is not None:
            client.close()
        logger.warning("Redis job lock unavailable for %s job_id=%s: %s", job_type, job_id, exc)
        return False

    if not acquired:
        client.close()
        return None
    return JobLock(key=key, token=token, client=client)


def release_job_lock(lock: JobLock | bool | None) -> None:
    if not isinstance(lock, JobLock):
        return
    try:
        current_token = lock.client.get(lock.key)
        if current_token == lock.token:
            lock.client.delete(lock.key)
    except RedisError as exc:
        logger.warning("Redis job lock release failed for %s: %s", lock.key, exc)
    finally:
        lock.client.close()
