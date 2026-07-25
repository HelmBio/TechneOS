"""App registry + runtime proxy service FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app_service.deployer import start_worker, stop_worker
from app_service.routes import apps, artifacts, launches, simple
from app_service.runtime_proxy import router as runtime_router
from app_service.seeds import reconcile_embedded_apps
from core.auth.openapi import install_permission_annotations
from core.config import get_settings
from core.database.postgres import dispose_engine
from core.exceptions import (
    AlreadyExistsError,
    AuthError,
    InsufficientPermissionsError,
    NotFoundError,
    PlatformError,
    ValidationError,
)

# Import models whose tables are referenced by ForeignKey so SQLAlchemy
# can resolve them when compiling the mapper for App / AppLaunch.
from core.models.user import Org, User  # noqa: F401
from core.openapi import short_operation_id


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    print(f"App service starting (env={settings.environment})")
    await start_worker()
    try:
        await reconcile_embedded_apps()
    except Exception as exc:
        print(f"App runtime reconciliation failed: {exc}")
    yield
    await stop_worker()
    await dispose_engine()
    print("App service stopped")


app = FastAPI(
    generate_unique_id_function=short_operation_id,
    title="TechneOS — Apps",
    description="Register and launch interactive web applications",
    version="0.1.0",
    lifespan=lifespan,
)


# --- Exception handlers ---


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": exc.message})


@app.exception_handler(AlreadyExistsError)
async def already_exists_handler(request: Request, exc: AlreadyExistsError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": exc.message})


@app.exception_handler(InsufficientPermissionsError)
async def insufficient_permissions_handler(
    request: Request, exc: InsufficientPermissionsError
) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": exc.message})


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": exc.message})


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.message})


@app.exception_handler(PlatformError)
async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": exc.message})


# --- Routes ---

settings = get_settings()
prefix = settings.api_v1_prefix

app.include_router(apps.router, prefix=f"{prefix}/apps", tags=["apps"])
app.include_router(launches.router, prefix=f"{prefix}/app-launches", tags=["app-launches"])
# Artifact publishing for the whole platform (apps + container tools + agents +
# pypi tools) — app-service is the single publisher, so the gateway proxies
# /api/v1/artifacts/{wheel,image} here.
app.include_router(artifacts.router, prefix=f"{prefix}/artifacts", tags=["artifacts"])
# PyPI Simple index (/simple/*) — served at root, unauthenticated, for uv/pip.
# The gateway forwards /simple/* here (it is in the gateway's PUBLIC_PREFIXES).
app.include_router(simple.router, tags=["simple"])
# Runtime reverse proxy — under /api/v1/apps/runtime so it flows through
# the gateway's standard auth middleware and routing.
app.include_router(runtime_router, prefix=f"{prefix}/apps/runtime", tags=["apps-runtime"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "app-service"}

# Document per-endpoint RBAC permissions in the OpenAPI schema.
install_permission_annotations(app)
