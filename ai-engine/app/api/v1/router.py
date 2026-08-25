from fastapi import APIRouter

from app.api.v1 import image, text, video

router = APIRouter()
router.include_router(text.router, prefix="/text", tags=["Text"])
router.include_router(image.router, prefix="/image", tags=["Image"])
router.include_router(video.router, prefix="/video", tags=["Video"])
