from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "gaim_ai_engine",
    broker=settings.celery_broker_url or settings.redis_url,
    backend=settings.celery_result_backend or settings.redis_url,
    include=[
        "app.workers.tasks.image_tasks",
        "app.workers.tasks.video_tasks",
    ],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    task_always_eager=settings.celery_task_always_eager,
    worker_concurrency=settings.celery_worker_concurrency,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_time_limit=settings.celery_task_time_limit,
    result_expires=settings.celery_result_expires,
    broker_connection_retry_on_startup=settings.celery_broker_connection_retry_on_startup,
    task_acks_late=settings.celery_task_acks_late,
    task_reject_on_worker_lost=settings.celery_task_reject_on_worker_lost,
    task_acks_on_failure_or_timeout=settings.celery_task_acks_on_failure_or_timeout,
    broker_transport_options={
        "visibility_timeout": settings.celery_broker_visibility_timeout,
    },
    task_routes={
        "app.workers.tasks.image_tasks.generate_image_task": {"queue": "image-queue"},
        "app.workers.tasks.video_tasks.generate_video_short_task": {"queue": "video-queue"},
        "app.workers.tasks.video_tasks.generate_video_task": {"queue": "video-queue"},
    },
)
