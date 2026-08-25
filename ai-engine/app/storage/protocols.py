from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    url: str
    content_type: str
    size_bytes: int


class StorageAdapter(Protocol):
    async def put_bytes(self, *, data: bytes, key: str, content_type: str) -> StoredObject:
        ...

    async def get_url(self, key: str) -> str:
        ...
