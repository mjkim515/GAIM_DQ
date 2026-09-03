import pytest

from app.core.exceptions import ProviderError


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1/reference.png",
        "http://localhost/reference.png",
        "http://10.0.0.5/reference.png",
        "http://192.168.1.10/reference.png",
        "ftp://example.com/reference.png",
    ],
)
def test_reference_image_rejects_unsafe_remote_urls(url):
    from app.services.image import references

    with pytest.raises(ProviderError):
        references._load_from_url(url)


def test_reference_image_rejects_domain_resolving_to_private_ip(monkeypatch):
    from app.services.image import references

    monkeypatch.setattr(references.socket, "getaddrinfo", lambda *args, **kwargs: [
        (None, None, None, None, ("10.0.0.5", 443)),
    ])

    with pytest.raises(ProviderError):
        references._load_from_url("https://internal.example/reference.png")


def test_reference_image_allows_public_https_url(monkeypatch):
    from io import BytesIO

    from app.services.image import references

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(references.socket, "getaddrinfo", lambda *args, **kwargs: [
        (None, None, None, None, ("93.184.216.34", 443)),
    ])
    monkeypatch.setattr(references, "urlopen", lambda *args, **kwargs: FakeResponse(b"image-bytes"))

    assert references._load_from_url("https://example.com/reference.png") == b"image-bytes"


def test_storage_public_url_still_reads_local_file(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.services.image import references

    storage_dir = tmp_path / "storage"
    image_dir = storage_dir / "images"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "reference.png"
    image_path.write_bytes(b"local-image-bytes")

    monkeypatch.setenv("STORAGE_BASE_DIR", str(storage_dir))
    monkeypatch.setenv("STORAGE_PUBLIC_BASE_URL", "http://127.0.0.1:8002/gaim/generated")
    get_settings.cache_clear()

    def fail_if_urlopen_called(*args, **kwargs):
        raise AssertionError("storage public URL should be read from local storage")

    monkeypatch.setattr(references, "urlopen", fail_if_urlopen_called)

    assert references._load_from_url(
        "http://127.0.0.1:8002/gaim/generated/images/reference.png"
    ) == b"local-image-bytes"
