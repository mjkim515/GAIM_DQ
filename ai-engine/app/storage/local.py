from pathlib import Path
from urllib.parse import quote

from app.core.exceptions import StorageError
from app.storage.protocols import StoredObject


class LocalFileStorageAdapter:
    def __init__(self, base_dir: Path, public_base_url: str):
        self.base_dir = base_dir
        self.public_base_url = public_base_url.rstrip("/")

    async def put_bytes(self, *, data: bytes, key: str, content_type: str) -> StoredObject:
        safe_key = self._safe_key(key)
        target = self.base_dir / safe_key
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(data)
        except OSError as exc:
            raise StorageError(f"Failed to write local object: {safe_key}") from exc
        return StoredObject(
            key=safe_key,
            url=await self.get_url(safe_key),
            content_type=content_type,
            size_bytes=len(data),
        )

    async def get_url(self, key: str) -> str:
        safe_key = self._safe_key(key)
        return f"{self.public_base_url}/{quote(safe_key)}"

    def _safe_key(self, key: str) -> str:
        normalized = key.strip().lstrip("/")
        if not normalized or ".." in Path(normalized).parts:
            raise StorageError("Invalid storage key")
        return normalized
