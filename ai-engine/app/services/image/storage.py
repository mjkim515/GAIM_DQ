from uuid import uuid4

from app.storage.factory import get_storage_adapter


async def store_image(data: bytes, extension: str = "png", content_type: str | None = None) -> str:
    content_type = content_type or f"image/{'jpeg' if extension == 'jpg' else extension}"
    storage = get_storage_adapter()
    stored = await storage.put_bytes(
        data=data,
        key=f"images/{uuid4()}.{extension}",
        content_type=content_type,
    )
    return stored.url
