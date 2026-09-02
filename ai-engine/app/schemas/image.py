import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import JobStatus

IMAGE_SIZE_PATTERN = re.compile(r"^\d+x\d+$")
IMAGE_ASPECT_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}

class ReferenceImage(BaseModel):
    image_url: str | None = None
    file_id: str | None = None
    b64_json: str | None = None
    mime_type: str = "image/png"

    @model_validator(mode="after")
    def require_one_reference(self):
        provided = [value for value in (self.image_url, self.file_id, self.b64_json) if value]
        if len(provided) != 1:
            raise ValueError("Provide exactly one of image_url, file_id, or b64_json")
        return self
    
class ImageRequest(BaseModel):
    purpose: Literal["promotion", "event", "brand", "홍보", "이벤트", "브랜드"]
    visual_mood: Literal[
        "bright",
        "warm_cozy",
        "moody",
        "clean_minimal",
        "premium",
        "vibrant",
    ] = "bright"
    channels: list[
        Literal[
            "instagram",
            "instagram_story",
            "instagram_reels",
            "sns",
            "blog",
            "naver_place",
            "banner",
            "general",
            "custom",
            "인스타",
            "SNS",
            "블로그",
            "네이버플레이스",
            "배너",
            "일반",
        ]
    ] = Field(min_length=1, max_length=5)
    image_prompt: str = Field(min_length=1, max_length=4000)
    reference_images: list[ReferenceImage] | None = Field(default=None, max_length=16)
    text_to_render: str | None = Field(default=None, max_length=1000)
    text_rendering: "TextRenderingRequest | None" = None
    n: int = Field(default=1, ge=1, le=4)

    @model_validator(mode="after")
    def derive_text_to_render(self):
        if self.text_rendering and not self.text_to_render:
            self.text_to_render = self.text_rendering.text
        return self

class ImageResponse(BaseModel):
    images: list[str]
    model_used: str
    provider: str
    
    
class ImageModelCandidate(BaseModel):
    rank: int
    provider: Literal["openai", "google", "local"]
    model: str
    operation: Literal["generate", "edit", "placeholder"]
    size: str
    n: int
    reason: str
    
class ImageCreateRouting(BaseModel):
    primary_channel: str
    final_prompt: str
    selected_rank: int
    selected: ImageModelCandidate
    attempted_models: list[ImageModelCandidate]
    fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class ImageCreateResponse(ImageResponse):
    routing: ImageCreateRouting


class ImageJobRequest(ImageRequest):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId", min_length=1, max_length=128)


class ImageJobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: str
    message: str


class ImageStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: JobStatus
    images: list[str] = Field(default_factory=list)
    provider: str | None = None
    model_used: str | None = Field(default=None, alias="modelUsed")
    error: str | None = None
    progress_pct: int | None = Field(default=None, alias="progressPct")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    

class ProviderImageRequest(BaseModel):
    provider: Literal["openai", "google"] = "openai"
    model: str | None = None
    prompt: str = Field(min_length=1, max_length=4000)
    reference_images: list[ReferenceImage] | None = Field(default=None, max_length=16)
    text_to_render: str | None = Field(default=None, max_length=1000)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    size: str = Field(default="1024x1024", description="Image size, e.g. 1024x1024, 1536x1024, 1024x1536, 2048x2048, or auto")
    quality: Literal["low", "medium", "high", "auto"] | None = None
    output_format: Literal["png", "jpeg", "webp"] = "png"
    background: Literal["transparent", "opaque", "auto"] = "auto"
    style: Literal["vivid", "natural"] = "vivid"
    n: int = Field(default=1, ge=1, le=4)

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        if value == "auto" or value in IMAGE_ASPECT_RATIOS:
            return value
        if not IMAGE_SIZE_PATTERN.match(value):
            raise ValueError("size must be 'auto' or '<width>x<height>'")
        width, height = (int(part) for part in value.split("x", 1))
        if width < 256 or height < 256:
            raise ValueError("size edges must be at least 256px")
        if width > 3840 or height > 3840:
            raise ValueError("size edges must be less than or equal to 3840px")
        return value


class ProviderImageGenerateWithReferenceRequest(BaseModel):
    provider: Literal["openai", "google"] = "openai"
    model: str | None = None
    prompt: str = Field(min_length=1, max_length=4000)
    reference_images: list[ReferenceImage] = Field(min_length=1, max_length=16)
    text_to_render: str | None = Field(default=None, max_length=1000)
    size: str = Field(default="1024x1024")
    quality: Literal["low", "medium", "high", "auto"] | None = None
    output_format: Literal["png", "jpeg", "webp"] = "png"
    background: Literal["transparent", "opaque", "auto"] = "auto"
    input_fidelity: Literal["low", "high"] = "high"
    n: int = Field(default=1, ge=1, le=4)

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        return ProviderImageRequest.validate_size(value)

class TextRenderingRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    language: Literal["ko", "en", "auto"] = "ko"
    placement: Literal["auto", "top", "center", "bottom", "left", "right"] = "auto"
    must_render_exactly: bool = True
    font_hint: str | None = Field(default=None, max_length=100)
    color_hint: str | None = Field(default=None, max_length=100)


class ImageIntentRequest(BaseModel):
    task: Literal[
        "generate",
        "edit",
        "inpaint",
        "outpaint",
        "background_replace",
        "style_transfer",
        "text_insert",
    ] = "generate"
    purpose: Literal["draft", "sns_post", "poster", "banner", "final_asset"] = "sns_post"
    channel: Literal[
        "instagram_feed",
        "instagram_story",
        "instagram_reels",
        "naver_place",
        "blog",
        "banner",
        "custom",
    ] = "instagram_feed"
    quality_priority: Literal["cost", "speed", "quality", "text_accuracy"] = "cost"
    text_importance: Literal["none", "low", "medium", "high"] = "none"
    prompt: str = Field(min_length=1, max_length=4000)
    reference_images: list[ReferenceImage] | None = Field(default=None, max_length=16)
    text_to_render: str | None = Field(default=None, max_length=1000)
    text_rendering: TextRenderingRequest | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    resolution_tier: Literal["auto", "512", "1k", "2k", "4k"] = "auto"
    output_format: Literal["png", "jpeg", "webp"] = "png"
    background: Literal["transparent", "opaque", "auto"] = "auto"
    style: Literal["vivid", "natural"] = "vivid"
    n: int = Field(default=1, ge=1, le=10)
    web_search: bool = False

    @model_validator(mode="after")
    def derive_text_to_render(self):
        if self.text_rendering and not self.text_to_render:
            self.text_to_render = self.text_rendering.text
        return self

    @field_validator("aspect_ratio")
    @classmethod
    def validate_aspect_ratio(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {
            "1:1",
            "3:4",
            "4:3",
            "9:16",
            "16:9",
            "4:1",
            "1:4",
            "8:1",
            "1:8",
        }:
            raise ValueError("unsupported aspect_ratio")
        return value

    @field_validator("size")
    @classmethod
    def validate_optional_size(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ProviderImageRequest.validate_size(value)

class ImageRoutingDecision(BaseModel):
    provider: Literal["openai", "google", "local"]
    model: str
    operation: Literal["generate", "edit", "placeholder"]
    size: str
    n: int
    reason: str
    attempted_models: list[ImageModelCandidate] = Field(default_factory=list)
    fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)

class ImageIntentResponse(ImageResponse):
    routing: ImageRoutingDecision
    
def image_request_to_reference_request(request: ProviderImageRequest) -> ProviderImageGenerateWithReferenceRequest:
    if not request.reference_images:
        raise ValueError("reference_images is required")
    return ProviderImageGenerateWithReferenceRequest(
        provider=request.provider,
        model=request.model,
        prompt=request.prompt,
        reference_images=request.reference_images,
        text_to_render=request.text_to_render,
        size=request.size,
        quality=request.quality,
        output_format=request.output_format,
        background=request.background,
        input_fidelity="high",
        n=request.n,
    )

class ImageModelInfo(BaseModel):
    provider: str
    default_model: str
    supported_models: list[str]
    default_quality: str
    supported_sizes: list[str]
    supported_qualities: list[str]
    supported_output_formats: list[str]
