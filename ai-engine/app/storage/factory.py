from functools import lru_cache

from app.config import get_settings
from app.storage.local import LocalFileStorageAdapter
from app.storage.protocols import StorageAdapter


@lru_cache
def get_storage_adapter() -> StorageAdapter:
    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalFileStorageAdapter(
            base_dir=settings.storage_base_dir,
            public_base_url=settings.storage_public_base_url,
        )
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
