"""Reverse proxy routes — forward requests to internal services.

In production with Kubernetes, service-to-service communication would use
K8s service discovery. For local development and the monolith-first approach,
the gateway proxies requests to individual service processes.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from starlette.requests import ClientDisconnect

from core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Service routing table
# Maps URL prefixes to backend service URLs
SERVICE_ROUTES: dict[str, str] = {}


def _get_service_routes() -> dict[str, str]:
    """Lazily initialize service routes from settings."""
    if not SERVICE_ROUTES:
        settings = get_settings()
        SERVICE_ROUTES.update(
            {
                "/admin": settings.auth_service_url + settings.api_v1_prefix,
                "/auth": settings.auth_service_url + settings.api_v1_prefix,
                "/users": settings.auth_service_url + settings.api_v1_prefix,
                "/orgs": settings.auth_service_url + settings.api_v1_prefix,
                "/teams": settings.auth_service_url + settings.api_v1_prefix,
                "/api-keys": settings.auth_service_url + settings.api_v1_prefix,
                "/datasets": settings.dataset_service_url + settings.api_v1_prefix,
                "/tools": settings.tool_service_url + settings.api_v1_prefix,
                "/tool-runs": settings.tool_service_url + settings.api_v1_prefix,
                "/compute-backends": settings.tool_service_url + settings.api_v1_prefix,
                "/compute-artifacts": settings.tool_service_url + settings.api_v1_prefix,
                "/task-runs": settings.task_service_url + settings.api_v1_prefix,
                "/pipelines": settings.pipeline_service_url + settings.api_v1_prefix,
                "/pipeline-runs": settings.pipeline_service_url + settings.api_v1_prefix,
                "/agents": settings.agent_service_url + settings.api_v1_prefix,
                "/agentic-runs": settings.agent_service_url + settings.api_v1_prefix,
                "/agentic-tasks": settings.agent_service_url + settings.api_v1_prefix,
                "/assistant": settings.agent_service_url + settings.api_v1_prefix,
                "/subscriptions": settings.notification_service_url + settings.api_v1_prefix,
                "/notifications": settings.notification_service_url + settings.api_v1_prefix,
                # All artifact publishing runs in app-service (the single
                # publisher — it holds the docker socket + registry creds). The
                # gateway holds no AWS/registry knowledge; it just routes here.
                # /simple/* is forwarded by routes/simple_proxy.py (root path).
                "/artifacts/image": settings.app_service_url + settings.api_v1_prefix,
                "/artifacts/wheel": settings.app_service_url + settings.api_v1_prefix,
                # Apps: runtime reverse proxy MUST come before /apps so its
                # longer prefix wins during iteration.
                "/apps/runtime": settings.app_service_url + settings.api_v1_prefix,
                "/apps": settings.app_service_url + settings.api_v1_prefix,
                "/app-launches": settings.app_service_url + settings.api_v1_prefix,
            }
        )
    return SERVICE_ROUTES


def _is_sse_request(request: Request, path: str) -> bool:
    """Check if the request expects a Server-Sent Events response."""
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return True
    # Known SSE endpoints
    if path.endswith("/stream"):
        return True
    return bool(path.endswith("/chat") and "assistant" in path)


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    # Excluded from the schema: this catch-all would otherwise be the only
    # operation the gateway documents. The real per-resource endpoints are
    # merged in from each backend service by gateway.openapi.
    include_in_schema=False,
)
async def proxy(request: Request, path: str) -> Response:
    """Forward requests to the appropriate backend service."""
    routes = _get_service_routes()

    # Find matching service
    target_url = None
    for prefix, service_url in routes.items():
        if f"/{path}".startswith(prefix):
            target_url = f"{service_url}/{path}"
            break

    if target_url is None:
        return Response(
            content='{"detail": "No service found for this path"}',
            status_code=404,
            media_type="application/json",
        )

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

    # Use streaming proxy for SSE endpoints to avoid buffering
    if _is_sse_request(request, path):
        return await _proxy_stream(target_url, request, headers, body)

    # Standard buffered proxy for normal requests
    return await _proxy_buffered(target_url, request, headers, body)


async def _proxy_buffered(
    target_url: str,
    request: Request,
    headers: dict[str, Any],
    body: bytes,
) -> Response:
    """Forward a request and return the full response (buffered)."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=300.0,
            )
        except httpx.HTTPError as e:
            logger.error(
                "Proxy request failed: %s %s — %s: %s",
                request.method,
                target_url,
                type(e).__name__,
                e,
            )
            return Response(
                content='{"detail": "Backend service unavailable"}',
                status_code=503,
                media_type="application/json",
            )

    # Strip headers that don't survive a httpx-decoded body. content-encoding
    # in particular: httpx decompresses gzip/br, so forwarding the original
    # encoding header would break the browser (ERR_CONTENT_DECODING_FAILED).
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )


async def _proxy_stream(
    target_url: str,
    request: Request,
    headers: dict[str, Any],
    body: bytes,
) -> Response:
    """Forward a request and stream the response back without buffering."""
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
    )
    try:
        resp = await client.send(
            client.build_request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
            ),
            stream=True,
        )
    except httpx.ConnectError:
        await client.aclose()
        return Response(
            content='{"detail": "Backend service unavailable"}',
            status_code=503,
            media_type="application/json",
        )

    # Filter out hop-by-hop headers that shouldn't be forwarded
    excluded = {"transfer-encoding", "connection", "keep-alive"}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}

    async def stream_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        content=stream_body(),
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type", "text/event-stream"),
    )
