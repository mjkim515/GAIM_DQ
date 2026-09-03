from dataclasses import dataclass

from app.config import get_settings
from app.core.exceptions import RequestValidationError


@dataclass(frozen=True)
class VideoModelCandidate:
    rank: int
    provider: str
    model: str
    reason: str


def build_video_short_candidates(
    model_tier: str,
    task: str = "textToVideo",
    settings=None,
    provider_override: str | None = None,
) -> list[VideoModelCandidate]:
    settings = settings or get_settings()
    if task == "referenceToVideo":
        model_tier = "standard"
    google_model = {
        "standard": settings.google_standard_video_model,
        "fast": settings.google_fast_video_model,
        "lite": settings.google_lite_video_model,
    }.get(model_tier)
    runway_model = _runway_model_for_task(model_tier, task, settings)
    if google_model is None or runway_model is None:
        raise RequestValidationError(f"Unsupported video model tier: {model_tier}")
    candidates = [
        VideoModelCandidate(
            rank=1,
            provider="google",
            model=google_model,
            reason="Veo remains the default video provider.",
        ),
        VideoModelCandidate(
            rank=2,
            provider="runway",
            model=runway_model,
            reason="Runway is the fallback if Veo is unavailable, retired, or unsupported.",
        ),
    ]
    if provider_override is None:
        return candidates
    if provider_override == "google":
        return [candidates[0]]
    if provider_override == "runway":
        return [
            VideoModelCandidate(
                rank=1,
                provider="runway",
                model=runway_model,
                reason="Runway provider override for direct testing.",
            )
        ]
    raise RequestValidationError(f"Unsupported video provider override: {provider_override}")


def _runway_model_for_task(model_tier: str, task: str, settings) -> str | None:
    if task == "textToVideo":
        return settings.runway_standard_video_model
    return {
        "standard": settings.runway_standard_video_model,
        "fast": settings.runway_fast_video_model,
        "lite": settings.runway_fast_video_model,
    }.get(model_tier)


def serialize_video_candidates(candidates: list[VideoModelCandidate]) -> list[dict[str, object]]:
    return [
        {
            "rank": candidate.rank,
            "provider": candidate.provider,
            "model": candidate.model,
            "reason": candidate.reason,
        }
        for candidate in candidates
    ]


def deserialize_video_candidates(items: list[dict[str, object]] | None) -> list[VideoModelCandidate]:
    if not items:
        return []
    return [
        VideoModelCandidate(
            rank=int(item["rank"]),
            provider=str(item["provider"]),
            model=str(item["model"]),
            reason=str(item.get("reason") or ""),
        )
        for item in items
    ]
