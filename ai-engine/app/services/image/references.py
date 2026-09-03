import ipaddress
import socket
from urllib.parse import urlparse
from urllib.request import urlopen

from app.config import get_settings
from app.core.exceptions import ProviderError
from app.core.media_limits import decode_limited_base64, read_limited_file, read_limited_response
from app.schemas.image import ReferenceImage


def build_edit_prompt(prompt: str, text_to_render: str | None) -> str:
    if not text_to_render:
        return prompt
    return (
        f"{prompt}\n\n"
        "다음 문구를 이미지 안에 보이도록 정확히 렌더링하고, "
        "깔끔하고 읽기 쉬운 타이포그래피로 표현하세요. "
        "렌더링할 문구도 GAIM 마케팅 안전 정책과 시각 콘텐츠 안전 정책을 따라야 합니다:\n"
        f"{text_to_render}"
    )


def load_reference_image_bytes(reference: ReferenceImage) -> bytes:
    settings = get_settings()
    if reference.b64_json:
        return decode_limited_base64(
            reference.b64_json,
            max_bytes=settings.max_image_reference_bytes,
            label="Image reference",
        )
    if reference.image_url:
        return _load_from_url(reference.image_url)
    raise ProviderError("file_id references are only supported by OpenAI edit requests")


def _load_from_url(image_url: str) -> bytes:
    settings = get_settings()
    public_base = settings.storage_public_base_url.rstrip("/")
    parsed = urlparse(image_url)
    public_parsed = urlparse(public_base)

    if image_url.startswith(public_base):
        relative_key = image_url[len(public_base):].lstrip("/")
        local_path = settings.storage_base_dir / relative_key
        if not local_path.exists():
            raise ProviderError(f"Local reference image was not found: {relative_key}")
        return read_limited_file(
            local_path,
            max_bytes=settings.max_image_reference_bytes,
            label="Image reference",
        )

    if parsed.hostname in {"localhost", "127.0.0.1"} and public_parsed.path:
        marker = public_parsed.path.rstrip("/") + "/"
        if marker in parsed.path:
            relative_key = parsed.path.split(marker, 1)[1]
            local_path = settings.storage_base_dir / relative_key
            if local_path.exists():
                return read_limited_file(
                    local_path,
                    max_bytes=settings.max_image_reference_bytes,
                    label="Image reference",
                )

    _validate_remote_reference_url(parsed)
    with urlopen(image_url, timeout=settings.reference_image_download_timeout_sec) as response:
        return read_limited_response(
            response,
            max_bytes=settings.max_image_reference_bytes,
            label="Image reference",
        )


def _validate_remote_reference_url(parsed) -> None:
    if parsed.scheme not in {"http", "https"}:
        raise ProviderError("Reference image URL must use http or https.")
    if not parsed.hostname:
        raise ProviderError("Reference image URL must include a hostname.")

    hostname = parsed.hostname
    try:
        _reject_private_address(ipaddress.ip_address(hostname))
        return
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderError("Reference image URL hostname could not be resolved.") from exc

    resolved_ips = {address[4][0] for address in addresses}
    if not resolved_ips:
        raise ProviderError("Reference image URL hostname could not be resolved.")
    for resolved_ip in resolved_ips:
        _reject_private_address(ipaddress.ip_address(resolved_ip))


def _reject_private_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ProviderError("Reference image URL points to a non-public network address.")
