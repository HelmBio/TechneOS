"""API Gateway — main FastAPI application.

The gateway is the single entry point for all client requests. It handles:
- Authentication (JWT and API key validation)
- Rate limiting
- Request routing to internal services
- Health/readiness checks
- Request/response logging
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from core.config import get_settings
from core.database.postgres import dispose_engine
from core.openapi import short_operation_id
from gateway.middleware.auth import AuthMiddleware
from gateway.middleware.client_version import ClientVersionMiddleware
from gateway.middleware.logging import RequestLoggingMiddleware
from gateway.openapi import install_openapi, swagger_ui_html
from gateway.routes.admin import router as admin_router
from gateway.routes.cli import router as cli_router
from gateway.routes.health import router as health_router
from gateway.routes.proxy import router as proxy_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown."""
    settings = get_settings()
    print(f"API Gateway starting (env={settings.environment})")
    yield
    await dispose_engine()
    from core.cache import close_valkey_client

    await close_valkey_client()
    print("API Gateway stopped")


def create_app() -> FastAPI:
    """Create and configure the API Gateway application."""
    settings = get_settings()

    app = FastAPI(
        # Matches the backend services, so the gateway's own operations read the
        # same as the ones merged in from them.
        generate_unique_id_function=short_operation_id,
        title="TechneOS — API Gateway",
        description="Unified entry point for all platform services",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,  # replaced below with a cookie-omitting Swagger UI
        redoc_url="/redoc",
    )

    # --- Custom middleware (applied bottom-up, executed top-down) ---
    # add_middleware() prepends, so the LAST one added is the OUTERMOST
    # (executed first). Order below: CORS -> ClientVersion -> Logging -> Auth -> route.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    # Outside AuthMiddleware so a stale client still gets told its version is the
    # problem when the mismatch is what produced the 401.
    app.add_middleware(ClientVersionMiddleware)

    # CORS must be outermost so it adds headers to ALL responses
    # (including 401 errors from AuthMiddleware).
    origins = (
        ["*"]
        if settings.debug
        else [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routes ---
    # Admin routes must be included before the catch-all proxy so specific
    # paths (e.g. /admin/storage/files/delete) are matched first.
    app.include_router(admin_router, prefix=settings.api_v1_prefix, tags=["admin"])
    app.include_router(health_router, tags=["health"])
    # Client distribution: unprefixed, since it is a download surface rather
    # than a versioned API resource.
    app.include_router(cli_router, tags=["cli"])
    app.include_router(
        proxy_router,
        prefix=settings.api_v1_prefix,
        tags=["proxy"],
    )

    # Replace the gateway's own (proxy-only) schema with one aggregated from the
    # downstream services, so /docs shows the real per-resource API.
    install_openapi(app)

    # Custom Swagger UI whose "Try it out" omits the session cookie, so a call is
    # authenticated only by a token pasted into Authorize (the lock icons then
    # mean what they say). The default /docs is disabled above.
    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return swagger_ui_html(app)

    return app


app = create_app()
