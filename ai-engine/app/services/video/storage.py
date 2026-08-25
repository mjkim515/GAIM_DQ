from uuid import uuid4

from app.storage.factory import get_storage_adapter


async def store_video(data: bytes, extension: str = "mp4", content_type: str = "video/mp4") -> str:
    storage = get_storage_adapter()
    stored = await storage.put_bytes(
        data=data,
        key=f"videos/{uuid4()}.{extension}",
        content_type=content_type,
    )
    return stored.url
