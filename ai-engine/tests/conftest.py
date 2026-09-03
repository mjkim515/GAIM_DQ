import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["AI_PROVIDER_MODE"] = "mock"
os.environ["WAS_INTERNAL_TOKEN"] = "test-token"
os.environ["WAS_CALLBACK_TIMEOUT_SEC"] = "5.0"
os.environ["STORAGE_PUBLIC_BASE_URL"] = "http://testserver/generated"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["CELERY_JOB_LOCK_ENABLED"] = "false"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/1"

from app.config import get_settings
from app.main import app
from app.storage.factory import get_storage_adapter


@pytest.fixture(autouse=True)
def clear_settings_cache(tmp_path):
    os.environ["STORAGE_BASE_DIR"] = str(tmp_path / "storage")
    get_settings.cache_clear()
    get_storage_adapter.cache_clear()
    yield
    get_settings.cache_clear()
    get_storage_adapter.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"X-Internal-Token": "test-token"}
