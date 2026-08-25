from contextlib import asynccontextmanager

from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as v1_router
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

settings = get_settings()
settings.storage_base_dir.mkdir(parents=True, exist_ok=True)

IMAGE_CREATE_SCHEMA_ORDER = [
    "ImageJobRequest",
    "ImageJobResponse",
    "ReferenceImage",
    "TextRenderingRequest",
]

TEST_IMAGE_SCHEMA_ORDER = [
    "ProviderImageRequest",
    "ProviderImageGenerateWithReferenceRequest",
    "ImageResponse",
    "ImageIntentRequest",
    "ImageIntentResponse",
    "ImageCreateResponse",
    "ImageCreateRouting",
    "ImageModelCandidate",
    "ImageRoutingDecision",
    "ImageModelInfo",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.storage_base_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="G-AIM AI Engine",
    description="FastAPI based AI content generation engine for G-AIM",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
    root_path=settings.root_path,
    root_path_in_servers=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(v1_router, prefix="/v1")
app.mount("/generated", StaticFiles(directory=settings.storage_base_dir), name="generated")


def _ordered_schemas(schemas: dict) -> dict:
    ordered_schema_names = IMAGE_CREATE_SCHEMA_ORDER + TEST_IMAGE_SCHEMA_ORDER
    ordered = {
        name: schemas[name]
        for name in ordered_schema_names
        if name in schemas
    }
    ordered.update(
        {
            name: schema
            for name, schema in schemas.items()
            if name not in ordered
        }
    )
    return ordered


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = openapi_schema.get("components", {})
    schemas = components.get("schemas")
    if schemas:
        components["schemas"] = _ordered_schemas(schemas)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


def _is_loopback_host(host: str) -> bool:
    hostname = urlsplit(f"//{host}").hostname or ""
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _public_url_parts(request: Request) -> tuple[str, str]:
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    host = forwarded_host or request.headers.get("host", request.url.netloc)
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme

    forwarded_prefix = request.headers.get("x-forwarded-prefix", "").split(",", 1)[0].strip()
    if forwarded_prefix:
        prefix = "/" + forwarded_prefix.strip("/")
    elif _is_loopback_host(host):
        prefix = ""
    else:
        prefix = "/" + settings.root_path.strip("/") if settings.root_path.strip("/") else ""

    return f"{scheme}://{host}", prefix


@app.get("/openapi.json", include_in_schema=False)
async def openapi_document(request: Request):
    origin, prefix = _public_url_parts(request)
    schema = {**app.openapi(), "servers": [{"url": f"{origin}{prefix}"}]}
    return JSONResponse(schema)


@app.get("/docs", include_in_schema=False)
async def swagger_document(request: Request):
    _, prefix = _public_url_parts(request)
    return get_swagger_ui_html(
        openapi_url=f"{prefix}/openapi.json",
        title=f"{app.title} - Swagger UI",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_document(request: Request):
    _, prefix = _public_url_parts(request)
    return get_redoc_html(
        openapi_url=f"{prefix}/openapi.json",
        title=f"{app.title} - ReDoc",
    )


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "env": settings.app_env,
        "storage_backend": settings.storage_backend,
        "ai_provider_mode": settings.ai_provider_mode,
    }
