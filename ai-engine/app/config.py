from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_port: int = 8002
    root_path: str = "/gaim"
    secret_key: str = "dev-secret-key"
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    was_base_url: str = "http://localhost:8080"
    was_internal_token: str = "change-this-internal-token"
    was_callback_timeout_sec: float = 1.0

    ai_provider_mode: Literal["mock", "live"] = "mock"
    openai_api_key: str = ""
    openai_default_image_model: str = "gpt-image-1.5"
    openai_default_image_quality: Literal["low", "medium", "high", "auto"] = "low"
    openai_image_models: list[str] = ["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"]
    openai_quality_image_model: str = "gpt-image-2"
    openai_standard_image_model: str = "gpt-image-1.5"
    openai_fast_image_model: str = "gpt-image-1-mini"
    openai_edit_image_model: str = "gpt-image-2"
    openai_text_accuracy_image_model: str = "gpt-image-2"
    openai_provider_timeout_sec: float = 60.0
    google_api_key: str = ""
    google_auth_mode: Literal["api_key", "vertex_ai"] = "api_key"
    google_default_image_model: str = "gemini-2.5-flash-image"
    google_provider_timeout_ms: int = 60_000
    gcp_image_location: str = "global"
    google_image_models: list[str] = ["gemini-2.5-flash-image"]
    gcp_project_id: str = ""
    gcp_location: str = "us-central1"
    gcp_service_account_json: str = ""

    @property
    def has_google_service_account(self) -> bool:
        return bool(self.gcp_service_account_json and self.gcp_service_account_json.strip() not in {"", "{}"})

    storage_backend: Literal["local"] = "local"
    storage_base_dir: Path = Field(default=Path("storage-data"))
    storage_public_base_url: str = "http://localhost:8000/generated"
    local_storage_retention_seconds: int = 7 * 24 * 60 * 60
    max_image_reference_bytes: int = 10 * 1024 * 1024
    max_video_input_image_bytes: int = 10 * 1024 * 1024
    reference_image_download_timeout_sec: float = 20.0
    gcs_bucket_name: str = "gaim-generated-assets"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_task_always_eager: bool = False
    celery_worker_concurrency: int = 3
    celery_worker_prefetch_multiplier: int = 1
    celery_task_soft_time_limit: int = 660
    celery_task_time_limit: int = 720
    celery_result_expires: int = 3600
    celery_broker_visibility_timeout: int = 900
    celery_broker_connection_retry_on_startup: bool = True
    celery_task_acks_late: bool = True
    celery_task_reject_on_worker_lost: bool = True
    celery_task_acks_on_failure_or_timeout: bool = True
    celery_task_retry_enabled: bool = False
    celery_task_retry_countdown: int = 15
    celery_job_lock_ttl: int = 900
    celery_job_lock_enabled: bool = True
    job_status_ttl_seconds: int = 12 * 60 * 60
    google_default_video_model: str = "veo-3.1-fast-generate-001"
    google_fast_video_model: str = "veo-3.1-fast-generate-001"
    google_standard_video_model: str = "veo-3.1-generate-001"
    google_lite_video_model: str = "veo-3.1-lite-generate-001"
    gcp_video_location: str = "us-central1"
    google_video_models: list[str] = [
        "veo-3.1-fast-generate-001",
        "veo-3.1-generate-001",
        "veo-3.1-lite-generate-001",
    ]
    runwayml_api_secret: str = ""
    runway_video_models: list[str] = ["gen4.5", "gen4_turbo"]
    runway_fast_video_model: str = "gen4_turbo"
    runway_standard_video_model: str = "gen4.5"
    runway_api_base_url: str = "https://api.dev.runwayml.com/v1"
    runway_api_version: str = "2024-11-06"
    runway_request_timeout_sec: float = 30.0
    runway_download_timeout_sec: float = 60.0
    video_poll_interval_sec: int = 10
    video_max_wait_sec: int = 600

    @property
    def is_live_ai_enabled(self) -> bool:
        return self.ai_provider_mode == "live"

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.celery_task_soft_time_limit <= self.video_max_wait_sec:
            raise ValueError("CELERY_TASK_SOFT_TIME_LIMIT must be greater than VIDEO_MAX_WAIT_SEC.")
        if self.celery_task_time_limit <= self.celery_task_soft_time_limit:
            raise ValueError("CELERY_TASK_TIME_LIMIT must be greater than CELERY_TASK_SOFT_TIME_LIMIT.")
        if self.celery_broker_visibility_timeout <= self.celery_task_time_limit:
            raise ValueError("CELERY_BROKER_VISIBILITY_TIMEOUT must be greater than CELERY_TASK_TIME_LIMIT.")

        if self.app_env.lower() not in {"production", "prod"}:
            return self

        errors: list[str] = []
        if self.secret_key in {"", "dev-secret-key", "replace-with-random-secret"}:
            errors.append("SECRET_KEY must be set to a production secret.")
        if self.was_internal_token in {"", "change-this-internal-token"}:
            errors.append("WAS_INTERNAL_TOKEN must be set to a production token.")
        if self.celery_task_always_eager:
            errors.append("CELERY_TASK_ALWAYS_EAGER must be false in production.")
        if self.was_base_url.startswith(("http://localhost", "http://127.0.0.1")):
            errors.append("WAS_BASE_URL must not point to localhost in production.")
        if self.is_live_ai_enabled:
            if not self.openai_api_key or self.openai_api_key.endswith("-placeholder"):
                errors.append("OPENAI_API_KEY must be set for live production mode.")
            if self.google_auth_mode == "api_key" and (
                not self.google_api_key or self.google_api_key.endswith("-placeholder")
            ):
                errors.append("GOOGLE_API_KEY must be set for live production api_key mode.")
            if self.google_auth_mode == "vertex_ai" and (
                not self.has_google_service_account or not self.gcp_project_id
            ):
                errors.append("GCP_PROJECT_ID and GCP_SERVICE_ACCOUNT_JSON must be set for vertex_ai mode.")

        if errors:
            raise ValueError("Invalid production settings: " + " ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
