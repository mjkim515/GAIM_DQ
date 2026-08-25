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
    task_routes={
        "app.workers.tasks.image_tasks.generate_image_task": {"queue": "image-queue"},
        "app.workers.tasks.video_tasks.generate_video_short_task": {"queue": "video-queue"},
        "app.workers.tasks.video_tasks.generate_video_task": {"queue": "video-queue"},
    },
)
