import base64
import binascii
from pathlib import Path
from urllib.response import addinfourl

from app.core.exceptions import RequestValidationError


def validate_bytes_size(data: bytes, *, max_bytes: int, label: str) -> bytes:
    if len(data) > max_bytes:
        raise RequestValidationError(f"{label} exceeds the {max_bytes} byte limit")
    return data


def decode_limited_base64(value: str, *, max_bytes: int, label: str) -> bytes:
    max_encoded_length = ((max_bytes + 2) // 3) * 4 + 4
    if len(value) > max_encoded_length:
        raise RequestValidationError(f"{label} exceeds the {max_bytes} byte limit")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RequestValidationError(f"{label} is not valid base64") from exc
    return validate_bytes_size(data, max_bytes=max_bytes, label=label)


def read_limited_file(path: Path, *, max_bytes: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise RequestValidationError(f"{label} could not be read") from exc
    if size > max_bytes:
        raise RequestValidationError(f"{label} exceeds the {max_bytes} byte limit")
    return validate_bytes_size(path.read_bytes(), max_bytes=max_bytes, label=label)


def read_limited_response(response: addinfourl, *, max_bytes: int, label: str) -> bytes:
    data = response.read(max_bytes + 1)
    return validate_bytes_size(data, max_bytes=max_bytes, label=label)
