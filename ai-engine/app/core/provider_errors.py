import asyncio
from urllib import error

from app.core.exceptions import (
    AIEngineError,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderServiceUnavailableError,
    ProviderTimeoutError,
    RequestValidationError,
)

OPENAI_PROVIDER_MESSAGES = {
    "auth": "OpenAI provider authentication failed.",
    "request": "OpenAI provider rejected the request.",
    "rate_limit": "OpenAI provider rate limit was reached. Please try again later.",
    "timeout": "OpenAI provider request timed out. Please try again later.",
    "connection": "OpenAI provider could not be reached. Please try again later.",
    "service": "OpenAI provider is temporarily unavailable. Please try again later.",
    "generic": "OpenAI provider request failed.",
}

GOOGLE_PROVIDER_MESSAGES = {
    "auth": "Google provider authentication failed.",
    "request": "Google provider rejected the request.",
    "rate_limit": "Google provider rate limit was reached. Please try again later.",
    "timeout": "Google provider request timed out. Please try again later.",
    "connection": "Google provider could not be reached. Please try again later.",
    "service": "Google provider is temporarily unavailable. Please try again later.",
    "generic": "Google provider request failed.",
}

RUNWAY_PROVIDER_MESSAGES = {
    "auth": "Runway provider authentication failed.",
    "request": "Runway provider rejected the request.",
    "rate_limit": "Runway provider rate limit was reached. Please try again later.",
    "timeout": "Runway provider request timed out. Please try again later.",
    "connection": "Runway provider could not be reached. Please try again later.",
    "service": "Runway provider is temporarily unavailable. Please try again later.",
    "generic": "Runway provider request failed.",
}

JOB_FAILURE_MESSAGES = {
    "validation": "요청값이 올바르지 않아 작업을 처리하지 못했습니다.",
    "auth": "외부 AI 서비스 인증 설정을 확인할 수 없어 작업을 처리하지 못했습니다.",
    "request": "외부 AI 서비스가 요청을 처리하지 못했습니다.",
    "rate_limit": "외부 AI 서비스 호출 한도에 도달했습니다. 잠시 후 다시 시도해주세요.",
    "timeout": "외부 AI 서비스 응답이 지연되어 작업을 완료하지 못했습니다. 잠시 후 다시 시도해주세요.",
    "connection": "외부 AI 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.",
    "service": "외부 AI 서비스가 일시적으로 불안정합니다. 잠시 후 다시 시도해주세요.",
    "generic": "작업을 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
}


def classify_openai_exception(exc: Exception) -> ProviderError:
    return _classify_provider_exception(exc, OPENAI_PROVIDER_MESSAGES)


def classify_google_exception(exc: Exception) -> ProviderError:
    return _classify_provider_exception(exc, GOOGLE_PROVIDER_MESSAGES)


def classify_runway_exception(exc: Exception) -> ProviderError:
    return _classify_provider_exception(exc, RUNWAY_PROVIDER_MESSAGES)


def public_job_error_message(exc: Exception) -> str:
    if isinstance(exc, RequestValidationError):
        return JOB_FAILURE_MESSAGES["validation"]
    if isinstance(exc, ProviderAuthenticationError):
        return JOB_FAILURE_MESSAGES["auth"]
    if isinstance(exc, ProviderRequestError):
        return JOB_FAILURE_MESSAGES["request"]
    if isinstance(exc, ProviderRateLimitError):
        return JOB_FAILURE_MESSAGES["rate_limit"]
    if isinstance(exc, ProviderTimeoutError) or isinstance(exc, TimeoutError):
        return JOB_FAILURE_MESSAGES["timeout"]
    if isinstance(exc, ProviderConnectionError) or isinstance(exc, (ConnectionError, OSError, error.URLError)):
        return JOB_FAILURE_MESSAGES["connection"]
    if isinstance(exc, ProviderServiceUnavailableError):
        return JOB_FAILURE_MESSAGES["service"]
    if isinstance(exc, ProviderError):
        return JOB_FAILURE_MESSAGES["generic"]
    if isinstance(exc, AIEngineError):
        return exc.message
    return JOB_FAILURE_MESSAGES["generic"]


def provider_warning_message(exc: Exception) -> str:
    if isinstance(exc, ProviderAuthenticationError):
        return "provider authentication failed"
    if isinstance(exc, ProviderRequestError):
        return "provider rejected the request"
    if isinstance(exc, ProviderRateLimitError):
        return "provider rate limit reached"
    if isinstance(exc, ProviderTimeoutError):
        return "provider request timed out"
    if isinstance(exc, ProviderConnectionError):
        return "provider connection failed"
    if isinstance(exc, ProviderServiceUnavailableError):
        return "provider temporarily unavailable"
    if isinstance(exc, ProviderError):
        return "provider request failed"
    if isinstance(exc, AIEngineError):
        return exc.message
    return "unexpected provider failure"


def _classify_provider_exception(exc: Exception, messages: dict[str, str]) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ProviderTimeoutError(messages["timeout"])
    if isinstance(exc, (ConnectionError, OSError, error.URLError)):
        return ProviderConnectionError(messages["connection"])

    status_code = _status_code(exc)
    class_name = exc.__class__.__name__.lower()

    if status_code in {401, 403} or "auth" in class_name or "permission" in class_name:
        return ProviderAuthenticationError(messages["auth"])
    if status_code in {400, 404, 409, 422} or "badrequest" in class_name or "invalid" in class_name:
        return ProviderRequestError(messages["request"])
    if status_code == 429 or "ratelimit" in class_name or "resourceexhausted" in class_name:
        return ProviderRateLimitError(messages["rate_limit"])
    if status_code == 408 or "timeout" in class_name or "deadline" in class_name:
        return ProviderTimeoutError(messages["timeout"])
    if "connection" in class_name or "unavailable" in class_name:
        return ProviderConnectionError(messages["connection"])
    if status_code is not None and status_code >= 500:
        return ProviderServiceUnavailableError(messages["service"])
    return ProviderError(messages["generic"])


def _status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None
