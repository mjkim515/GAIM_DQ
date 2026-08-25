from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import JobStatus


class VideoRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId", min_length=1, max_length=128)
    model: str = "fast"
    prompt: str = Field(min_length=1, max_length=4000)
    duration_seconds: int = Field(default=4, ge=3, le=8)
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"

    @field_validator("duration_seconds")
    @classmethod
    def normalize_veo_duration(cls, value: int) -> int:
        if value <= 4:
            return 4
        if value <= 6:
            return 6
        return 8


VideoShortTask = Literal["textToVideo", "imageToVideo", "referenceToVideo"]
VideoShortAspectRatio = Literal["9:16", "16:9"]
VideoShortDuration = Literal[4, 6, 8]
VideoShortModelTier = Literal["standard", "fast", "lite"]
VideoShortPlatform = Literal["youtube_shorts", "instagram_reels", "tiktok", "naver_clip"]
VideoShortProviderOverride = Literal["google", "runway"]


class VideoShortMediaInput(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "gcsUri": "gs://gaim-generated-assets/video-shorts/start-frame.png",
                "mimeType": "image/png",
            }
        },
    )

    gcs_uri: str | None = Field(default=None, alias="gcsUri")
    bytes_base64_encoded: str | None = Field(default=None, alias="bytesBase64Encoded")
    mime_type: Literal["image/png", "image/jpeg"] = Field(alias="mimeType")

    @model_validator(mode="after")
    def require_single_media_source(self):
        provided = [value for value in (self.gcs_uri, self.bytes_base64_encoded) if value]
        if len(provided) != 1:
            raise ValueError("Provide exactly one of gcsUri or bytesBase64Encoded")
        return self


class VideoShortInput(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "image": {
                    "gcsUri": "gs://gaim-generated-assets/video-shorts/start-frame.png",
                    "mimeType": "image/png",
                },
                "lastFrame": {
                    "gcsUri": "gs://gaim-generated-assets/video-shorts/end-frame.png",
                    "mimeType": "image/png",
                },
            }
        },
    )

    image: VideoShortMediaInput | None = None
    last_frame: VideoShortMediaInput | None = Field(default=None, alias="lastFrame")
    reference_images: list[VideoShortMediaInput] | None = Field(
        default=None,
        min_length=1,
        max_length=3,
        alias="referenceImages",
    )

    @model_validator(mode="after")
    def validate_input_sources(self):
        if self.reference_images and (self.image or self.last_frame):
            raise ValueError("referenceImages cannot be combined with image or lastFrame")
        if self.last_frame and not self.image:
            raise ValueError("lastFrame requires image")
        return self

    @property
    def has_media(self) -> bool:
        return bool(self.image or self.last_frame or self.reference_images)


class VideoShortAdvancedOverrides(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "sampleCount": 1,
                "resolution": "720p",
                "enhancePrompt": True,
                "generateAudio": True,
                "compressionQuality": "optimized",
                "resizeMode": "crop",
                "negativePrompt": "blurry, low quality",
            }
        },
    )

    sample_count: Literal[1, 2, 3, 4] | None = Field(
        default=None,
        alias="sampleCount",
        description="Override output count. If omitted, ai-engine uses 1.",
        json_schema_extra={"example": 1},
    )
    resolution: Literal["720p", "1080p"] | None = Field(
        default=None,
        description="Override output resolution. If omitted, ai-engine uses 720p.",
        json_schema_extra={"example": "720p"},
    )
    negative_prompt: str | None = Field(
        default=None,
        max_length=4000,
        alias="negativePrompt",
        json_schema_extra={"example": "blurry, low quality"},
    )
    person_generation: Literal["dont_allow", "allow_adult", "allowAll"] | None = Field(
        default=None,
        alias="personGeneration",
    )
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    enhance_prompt: bool | None = Field(
        default=None,
        alias="enhancePrompt",
        description="Override prompt enhancement. If omitted, ai-engine uses true.",
        json_schema_extra={"example": True},
    )
    generate_audio: bool | None = Field(
        default=None,
        alias="generateAudio",
        description="Override audio generation. If omitted, ai-engine uses true.",
        json_schema_extra={"example": True},
    )
    compression_quality: Literal["optimized", "lossless"] | None = Field(
        default=None,
        alias="compressionQuality",
        description="Override compression quality. If omitted, ai-engine uses optimized.",
        json_schema_extra={"example": "optimized"},
    )
    resize_mode: Literal["pad", "crop"] | None = Field(
        default=None,
        alias="resizeMode",
        description="Override image resize mode. If omitted, ai-engine uses crop.",
        json_schema_extra={"example": "crop"},
    )
    storage_uri: str | None = Field(default=None, alias="storageUri")
    pubsub_topic: str | None = Field(default=None, alias="pubsubTopic")


class VideoShortCreateRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
                    "prompt": "벚꽃이 만발한 호숫가 근처를 골드리트리버와 함께 한 남자가 걷고 있어",
                    "model": "fast",
                    "platform": "youtube_shorts",
                    "task": "textToVideo",
                    "aspectRatio": "9:16",
                    "durationSeconds": 8,
                    "advanced": {
                        "generateAudio": True,
                    },
                    "metadata": {
                        "campaignId": "campaign-1",
                    },
                },
                {
                    "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
                    "prompt": "이 이미지를 시작 프레임으로 자연스럽게 움직이는 숏폼 광고 생성",
                    "model": "fast",
                    "platform": "instagram_reels",
                    "task": "imageToVideo",
                    "aspectRatio": "9:16",
                    "durationSeconds": 8,
                    "input": {
                        "image": {
                            "gcsUri": "gs://gaim-generated-assets/video-shorts/start-frame.png",
                            "mimeType": "image/png",
                        }
                    },
                },
                {
                    "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
                    "prompt": "레퍼런스 이미지를 참고해서 제품 중심 숏폼 광고 생성",
                    "model": "standard",
                    "platform": "tiktok",
                    "task": "referenceToVideo",
                    "aspectRatio": "9:16",
                    "durationSeconds": 8,
                    "input": {
                        "referenceImages": [
                            {
                                "gcsUri": "gs://gaim-generated-assets/video-shorts/reference-1.png",
                                "mimeType": "image/png",
                            }
                        ]
                    },
                },
            ]
        },
    )

    job_id: str = Field(alias="jobId", min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=4000)
    model: VideoShortModelTier = "fast"
    platform: VideoShortPlatform | None = None
    task: VideoShortTask | None = None
    aspect_ratio: VideoShortAspectRatio = Field(default="9:16", alias="aspectRatio")
    duration_seconds: VideoShortDuration = Field(default=8, alias="durationSeconds")
    provider_override: VideoShortProviderOverride | None = Field(
        default=None,
        alias="providerOverride",
        description="ai-engine Swagger/provider diagnostics only. Omit for production policy: Veo first, Runway fallback.",
    )
    input: VideoShortInput | None = None
    advanced: VideoShortAdvancedOverrides | None = None
    metadata: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_video_short_inputs(self):
        if self.task == "imageToVideo" and not (self.input and self.input.image):
            raise ValueError("imageToVideo requires image")
        if self.task == "referenceToVideo" and not (self.input and self.input.reference_images):
            raise ValueError("referenceToVideo requires referenceImages")
        if self.task == "textToVideo" and self.input and self.input.has_media:
            raise ValueError("textToVideo cannot include image, lastFrame, or referenceImages")
        return self

    @property
    def inferred_task(self) -> str:
        if self.task:
            return self.task
        if self.input and self.input.reference_images:
            return "referenceToVideo"
        if self.input and self.input.image:
            return "imageToVideo"
        return "textToVideo"


class ResolvedVideoShortRequest(BaseModel):
    provider_model: str
    provider: str = "google"
    provider_candidates: list[dict[str, object]] = Field(default_factory=list)
    prompt: str
    final_prompt: str
    task: VideoShortTask
    platform: VideoShortPlatform | None = None
    aspect_ratio: VideoShortAspectRatio
    duration_seconds: VideoShortDuration
    input: VideoShortInput | None = None
    sample_count: Literal[1, 2, 3, 4]
    resolution: Literal["720p", "1080p"]
    enhance_prompt: bool
    generate_audio: bool
    compression_quality: Literal["optimized", "lossless"]
    resize_mode: Literal["pad", "crop"]
    negative_prompt: str | None = None
    person_generation: Literal["dont_allow", "allow_adult", "allowAll"] | None = None
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    storage_uri: str | None = None
    pubsub_topic: str | None = None
    metadata: dict[str, object] | None = None


class VideoJobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: JobStatus
    message: str


class VideoStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: JobStatus
    video_url: str | None = Field(default=None, alias="videoUrl")
    error: str | None = None
    progress_pct: int | None = Field(default=None, alias="progressPct")
    provider: str | None = None
    model_used: str | None = Field(default=None, alias="modelUsed")
    fallback_used: bool | None = Field(default=None, alias="fallbackUsed")
    warnings: list[str] = Field(default_factory=list)
