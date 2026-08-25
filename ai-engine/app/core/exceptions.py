from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas.common import ErrorResponse


class AIEngineError(Exception):
    status_code = 500
    code = "AI_ENGINE_ERROR"
    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None):
        self.message = message
        if retryable is not None:
            self.retryable = retryable
        super().__init__(message)


class ProviderError(AIEngineError):
    status_code = 502
    code = "PROVIDER_ERROR"


class ProviderAuthenticationError(ProviderError):
    code = "PROVIDER_AUTHENTICATION_ERROR"


class ProviderRequestError(ProviderError):
    code = "PROVIDER_REQUEST_ERROR"


class ProviderRateLimitError(ProviderError):
    status_code = 429
    code = "PROVIDER_RATE_LIMIT_ERROR"
    retryable = True


class ProviderTimeoutError(ProviderError):
    status_code = 504
    code = "PROVIDER_TIMEOUT_ERROR"
    retryable = True


class ProviderConnectionError(ProviderError):
    status_code = 503
    code = "PROVIDER_CONNECTION_ERROR"
    retryable = True


class ProviderServiceUnavailableError(ProviderError):
    status_code = 503
    code = "PROVIDER_SERVICE_UNAVAILABLE"
    retryable = True


class RequestValidationError(AIEngineError):
    status_code = 400
    code = "REQUEST_VALIDATION_ERROR"


class StorageError(AIEngineError):
    status_code = 500
    code = "STORAGE_ERROR"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AIEngineError)
    async def handle_ai_engine_error(request: Request, exc: AIEngineError):
        payload = ErrorResponse(code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())
