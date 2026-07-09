"""Task service FastAPI application — runtime side of human tasks."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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

# Side-effect imports so SQLAlchemy can resolve string-based FK references
# when the mapper is first configured.
from core.models.pipeline import PipelineRun, PipelineStepRun  # noqa: F401
from core.models.task_run import TaskRun, TaskRunArtifact, TaskRunEvent  # noqa: F401
from core.models.tool import HumanConfig, Tool, ToolVersion  # noqa: F401
from core.models.user import Org, Team, User  # noqa: F401
from task_service.routes import runs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    print(f"Task service starting (env={settings.environment})")
    yield
    await dispose_engine()
    print("Task service stopped")


app = FastAPI(
    title="TechneOS — Task Service",
    description="Runtime for human-typed tools: task runs, assignments, lifecycle, files",
    version="0.1.0",
    lifespan=lifespan,
)


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


settings = get_settings()
prefix = settings.api_v1_prefix

app.include_router(runs.router, prefix=f"{prefix}/task-runs", tags=["task-runs"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "task"}
