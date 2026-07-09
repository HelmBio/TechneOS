"""Pipeline orchestration service FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.database.postgres import dispose_engine
from core.exceptions import (
    AlreadyExistsError,
    AuthError,
    ConflictError,
    InsufficientPermissionsError,
    NotFoundError,
    PlatformError,
    ValidationError,
)
from pipeline_service.routes import monitoring, pipelines, runs, versions


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown."""
    settings = get_settings()
    print(f"Pipeline service starting (env={settings.environment})")
    yield
    await dispose_engine()
    print("Pipeline service stopped")


app = FastAPI(
    title="TechneOS — Pipeline Service",
    description="Define, submit, and track computational pipelines",
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


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
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

app.include_router(pipelines.router, prefix=f"{prefix}/pipelines", tags=["pipelines"])
app.include_router(
    versions.router,
    prefix=f"{prefix}/pipelines/{{pipeline_id}}/versions",
    tags=["pipeline-versions"],
)
app.include_router(runs.router, prefix=f"{prefix}/pipeline-runs", tags=["pipeline-runs"])
app.include_router(
    monitoring.router, prefix=f"{prefix}/pipeline-runs", tags=["pipeline-monitoring"]
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "pipeline"}
