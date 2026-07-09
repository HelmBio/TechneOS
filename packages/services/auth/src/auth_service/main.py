"""Auth service FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from auth_service.routes import (
    admin,
    api_keys,
    auth,
    buckets,
    labels,
    llm_providers,
    orgs,
    teams,
    users,
)
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown."""
    settings = get_settings()
    print(f"Auth service starting (env={settings.environment})")
    yield
    await dispose_engine()
    print("Auth service stopped")


app = FastAPI(
    title="TechneOS — Auth Service",
    description="User authentication, organization management, and RBAC",
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

app.include_router(auth.router, prefix=f"{prefix}/auth", tags=["auth"])
app.include_router(users.router, prefix=f"{prefix}/users", tags=["users"])
app.include_router(orgs.router, prefix=f"{prefix}/orgs", tags=["organizations"])
app.include_router(teams.router, prefix=f"{prefix}/orgs/{{org_id}}/teams", tags=["teams"])
app.include_router(teams.flat_router, prefix=f"{prefix}/teams", tags=["teams"])
app.include_router(
    llm_providers.router, prefix=f"{prefix}/orgs/{{org_id}}/llm-providers", tags=["llm-providers"]
)
app.include_router(buckets.router, prefix=f"{prefix}/orgs/{{org_id}}/buckets", tags=["buckets"])
app.include_router(api_keys.router, prefix=f"{prefix}/api-keys", tags=["api-keys"])
app.include_router(admin.router, prefix=f"{prefix}/admin", tags=["admin"])
app.include_router(labels.router, prefix=f"{prefix}/admin", tags=["labels"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "auth"}
