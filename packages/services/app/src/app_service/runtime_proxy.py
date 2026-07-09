"""Reverse proxy for embedded App containers.

Mounted at ``/apps/runtime/{slug}/{rest:path}``. Resolves the App by slug,
checks access, and forwards HTTP requests to the container's
``runtime_endpoint``. WebSocket support is deferred — apps that need WS
should add it explicitly in a follow-up.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.scope import check_resource_access
from core.database.postgres import get_async_session
from core.models.app import App
from core.models.common import TokenPayload

router = APIRouter()

# Hop-by-hop headers (RFC 7230) that must not be forwarded.
# We also strip `content-encoding` and `content-length` from the upstream
# response because httpx auto-decompresses the body — passing the original
# encoding header through would make the browser try to decode plain bytes
# and fail with ERR_CONTENT_DECODING_FAILED.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "content-encoding",
}


# Match the *entire* remaining path as a single converter and split out
# the slug ourselves. The earlier shape `/{slug}/{rest_path:path}` only
# matched when there was a slash after the slug, so requests ending in
# the bare slug (e.g. `/api/v1/apps/runtime/structure-viewer`) triggered
# FastAPI's redirect_slashes — and that 307's Location header is built
# from the upstream Host (the gateway pops the public Host before
# proxying, so app-service sees its internal compose name and emits
# Location: http://app-service:8007/...). The browser then tries to
# follow that absolute, plain-HTTP URL and the page fails on mixed
# content. By accepting any trailing form here we never need the
# redirect.
@router.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy_runtime(
    full_path: str,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    slug, _sep, rest_path = full_path.partition("/")
    if not slug:
        raise HTTPException(status_code=404, detail="App slug required")
    result = await session.execute(select(App).where(App.slug == slug))
    app = result.scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail=f"App '{slug}' not found")

    if app.launch_mode != "embedded":
        raise HTTPException(status_code=400, detail="App is not an embedded App")

    if app.runtime_status != "active" or not app.runtime_endpoint:
        raise HTTPException(
            status_code=409,
            detail=f"App is not running (runtime_status={app.runtime_status})",
        )

    check_resource_access(current_user, app, resource_name="app")

    target = f"http://{app.runtime_endpoint}/{rest_path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    # Identity passthrough — apps can trust these because the proxy added them.
    fwd_headers["X-TechneOS-User-Id"] = current_user.sub
    if current_user.org_id:
        fwd_headers["X-TechneOS-Org-Id"] = current_user.org_id
    if current_user.email:
        fwd_headers["X-TechneOS-User-Email"] = current_user.email

    body = await request.body()
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        try:
            upstream = await client.request(
                request.method,
                target,
                headers=fwd_headers,
                content=body,
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504, detail="Upstream app container timed out"
            ) from None
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot connect to app container at {app.runtime_endpoint}",
            ) from None
        except httpx.HTTPError:
            raise HTTPException(
                status_code=502, detail="Error communicating with app container"
            ) from None

    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("content-type"),
    )
