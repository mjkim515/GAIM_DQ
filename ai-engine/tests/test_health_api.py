def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["storage_backend"] == "local"

def test_openapi_image_create_schemas_are_listed_before_test_schemas(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema_names = set(response.json()["components"]["schemas"])
    assert "ImageJobRequest" in schema_names
    assert "ImageJobResponse" in schema_names
    assert "ProviderImageRequest" in schema_names
    assert "ImageIntentRequest" in schema_names
    assert "ImageCreateResponse" not in schema_names

def test_swagger_public_urls_follow_local_and_production_requests():
    from starlette.requests import Request

    from app.main import _public_url_parts

    def build_request(headers):
        return Request({
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/openapi.json",
            "root_path": "",
            "query_string": b"",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "server": ("127.0.0.1", 8002),
            "client": ("127.0.0.1", 50000),
        })

    local = build_request({"host": "127.0.0.1:8002"})
    production = build_request({
        "host": "ai.idq.co.kr",
        "x-forwarded-host": "ai.idq.co.kr",
        "x-forwarded-proto": "https",
    })

    assert _public_url_parts(local) == ("http://127.0.0.1:8002", "")
    assert _public_url_parts(production) == ("https://ai.idq.co.kr", "/gaim")
