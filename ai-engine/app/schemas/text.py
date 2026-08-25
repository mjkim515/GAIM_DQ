from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TextModel = Literal["gpt-4o-mini", "gpt-5.5", "auto"]
Language = Literal["ko", "en"]
BrandMode = Literal["profile_summary", "brand_ad_copy", "brand_image_prompt"]
RefineMode = Literal["content_prompt_rewrite", "copy_rewrite"]
MarketingContentType = Literal["product_detail", "ad_copy", "sns_post", "customer_message"]
MarketingPurpose = Literal[
    "instagram_promotion",
    "blog_promotion",
    "product_detail_page",
    "ad_click",
    "customer_response",
]
MarketingTone = Literal["emotional", "practical", "premium", "lively", "professional"]
MarketingTextLength = Literal["short", "medium", "long"]

BRAND_MODE_DESCRIPTION = (
    "선택 가능 모드: profile_summary(브랜드 소개 요약), "
    "brand_ad_copy(브랜드 광고 카피), "
    "brand_image_prompt(브랜드 이미지 프롬프트)."
)
REFINE_MODE_DESCRIPTION = (
    "선택 가능 모드: content_prompt_rewrite(이미지/영상 등 콘텐츠 생성 프롬프트 재작성), "
    "copy_rewrite(문구 재작성)."
)


class TextRequest(BaseModel):
    model: str = "gpt-4o-mini"
    prompt: str = Field(min_length=1, max_length=8000)
    business_info: dict[str, Any] | None = None
    content_type: Literal["sns", "banner", "email", "push"] = "sns"
    max_tokens: int = Field(default=500, ge=1, le=4000)


class TextResponse(BaseModel):
    content: str
    model_used: str
    tokens_used: int | None = None


class BrandProfile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    brand_voice: str | None = Field(default=None, max_length=500)
    target_audience: str | None = Field(default=None, max_length=500)
    strengths: list[str] = Field(default_factory=list, max_length=20)


class TextConstraints(BaseModel):
    max_tokens: int = Field(default=500, ge=1, le=4000)
    max_text_length: int | None = Field(default=None, ge=1, le=4000)
    number_of_variations: int = Field(default=1, ge=1, le=10)
    must_include: list[str] = Field(default_factory=list, max_length=30)
    must_avoid: list[str] = Field(default_factory=list, max_length=30)
    allow_hashtags: bool = False
    allow_emoji: bool = False


def default_text_constraints() -> TextConstraints:
    return TextConstraints()


class MarketingTextInput(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    purpose: MarketingPurpose
    tone: MarketingTone
    target_audience: str | None = Field(default=None, max_length=300)
    highlight_points: list[str] = Field(default_factory=list, max_length=10)


class MarketingTextOptions(BaseModel):
    length: MarketingTextLength = "short"
    number_of_variations: int = Field(default=3, ge=1, le=10)
    must_include: list[str] = Field(default_factory=list, max_length=20)
    must_avoid: list[str] = Field(default_factory=list, max_length=20)
    allow_hashtags: bool = False
    allow_emoji: bool = False
    max_tokens: int = Field(default=500, ge=1, le=4000)


class MarketingTextRequest(BaseModel):
    content_type: MarketingContentType
    input: MarketingTextInput
    options: MarketingTextOptions = Field(default_factory=MarketingTextOptions)


class _TextGenerationSettingsMixin:
    @property
    def constraints(self) -> TextConstraints:
        return default_text_constraints()


class BrandTextRequest(_TextGenerationSettingsMixin, BaseModel):
    model: TextModel = "gpt-4o-mini"
    mode: BrandMode = Field(description=BRAND_MODE_DESCRIPTION)
    language: Language = "ko"
    brand: BrandProfile


class RefineInput(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class RefineTarget(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    channel: str | None = Field(default=None, max_length=80)
    platform: str | None = Field(default=None, max_length=80)
    tone: str | None = Field(default=None, max_length=120)
    format: str | None = Field(default=None, max_length=120)
    visual_mood: str | None = Field(default=None, max_length=120, alias="visualMood")
    aspect_ratio: str | None = Field(default=None, max_length=40, alias="aspectRatio")
    duration_seconds: int | None = Field(default=None, ge=1, le=120, alias="durationSeconds")


class RefineTextRequest(_TextGenerationSettingsMixin, BaseModel):
    model: TextModel = "auto"
    mode: RefineMode = Field(description=REFINE_MODE_DESCRIPTION)
    language: Language = "ko"
    brand: BrandProfile | None = None
    input: RefineInput
    target: RefineTarget = Field(default_factory=RefineTarget)
