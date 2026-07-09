"""Tool registry service FastAPI application."""

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

# Import models whose tables are referenced by ForeignKey so SQLAlchemy
# can resolve them when compiling the mapper for Tool / ToolVersion.
from core.models.artifact import ComputeArtifact  # noqa: F401
from core.models.compute_backend import ComputeBackend  # noqa: F401
from core.models.pipeline import PipelineRun  # noqa: F401
from core.models.user import Org, User  # noqa: F401
from tool_service.routes import (
    compute_artifacts,
    compute_backends,
    runs,
    tools,
    versions,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown."""
    settings = get_settings()
    print(f"Tool registry service starting (env={settings.environment})")
    yield
    await dispose_engine()
    print("Tool registry service stopped")


app = FastAPI(
    title="TechneOS — Tool Registry",
    description="Register, version, and discover computational tools",
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

app.include_router(tools.router, prefix=f"{prefix}/tools", tags=["tools"])
app.include_router(
    versions.router,
    prefix=f"{prefix}/tools/{{tool_id}}/versions",
    tags=["tool-versions"],
)
app.include_router(runs.router, prefix=f"{prefix}/tool-runs", tags=["tool-runs"])
app.include_router(runs.tool_scoped_router, prefix=f"{prefix}/tools", tags=["tool-runs"])
app.include_router(
    compute_backends.router,
    prefix=f"{prefix}/compute-backends",
    tags=["compute-backends"],
)
app.include_router(
    compute_artifacts.router,
    prefix=f"{prefix}/compute-artifacts",
    tags=["compute-artifacts"],
)
# /task-runs is now served by task-service (see packages/services/task).


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "tool-registry"}
