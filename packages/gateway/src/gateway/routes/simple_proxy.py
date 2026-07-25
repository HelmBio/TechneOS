"""Root-level PyPI Simple index proxy — forwards ``/simple/*`` to app-service.

app-service is the platform's artifact publisher and serves the CodeArtifact-
authed index read; the gateway just routes ``/simple/*`` there. Kept separate
from the ``/api/v1`` catch-all proxy because the Simple index is served at the
root for uv/pip, and unauthenticated (``/simple/`` is in the auth middleware's
PUBLIC_PREFIXES). The gateway holds no index credentials.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from starlette.requests import ClientDisconnect

from core.config import get_settings
from gateway.routes.proxy import _proxy_buffered

router = APIRouter()


@router.api_route("/simple/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def simple_proxy(request: Request, path: str = "") -> Response:
    """Forward the Simple index request to app-service, unchanged."""
    settings = get_settings()
    target_url = f"{settings.app_service_url}{request.url.path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    try:
        body = await request.body()
    except ClientDisconnect:
        return Response(
            content='{"detail": "Client disconnected"}',
            status_code=499,
            media_type="application/json",
        )
    return await _proxy_buffered(target_url, request, headers, body)
