from app.config import Settings, get_settings
from app.storage.factory import get_storage_adapter
from app.storage.protocols import StorageAdapter


def settings_dependency() -> Settings:
    return get_settings()


def storage_dependency() -> StorageAdapter:
    return get_storage_adapter()
