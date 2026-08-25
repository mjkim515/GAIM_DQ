from enum import StrEnum

from pydantic import BaseModel


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ErrorResponse(BaseModel):
    code: str
    message: str
