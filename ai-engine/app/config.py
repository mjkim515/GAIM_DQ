from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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
    google_api_key: str = ""
    google_auth_mode: Literal["api_key", "vertex_ai"] = "api_key"
    google_default_image_model: str = "gemini-2.5-flash-image"
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
    gcs_bucket_name: str = "gaim-generated-assets"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_task_always_eager: bool = False
    celery_worker_concurrency: int = 3
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
    video_poll_interval_sec: int = 10
    video_max_wait_sec: int = 600

    @property
    def is_live_ai_enabled(self) -> bool:
        return self.ai_provider_mode == "live"


@lru_cache
def get_settings() -> Settings:
    return Settings()
