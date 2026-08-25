from fastapi import Header, HTTPException, status

from app.config import get_settings


async def verify_internal_token(x_internal_token: str = Header(...)) -> None:
    settings = get_settings()
    if x_internal_token != settings.was_internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )
