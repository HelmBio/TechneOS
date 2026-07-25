"""PyPI Simple API proxy — served at the root (``/simple/*``), unauthenticated.

app-service is the platform's artifact publisher, so it also serves the index
read side that uv/pip resolve against. The gateway forwards ``/simple/*`` here
(it is in the gateway's PUBLIC_PREFIXES, so no token is required). These routes
carry no auth dependency by design — resolution is anonymous; the CodeArtifact
read token is the *server's*, minted in :mod:`app_service.publish`.
"""

from __future__ import annotations

import base64
import html
import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response

from app_service.publish import (
    index_is_codeartifact,
    list_codeartifact_packages,
    resolve_index_read_credentials,
)
from core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Response headers we never forward from the underlying index.
#   - content-encoding / content-length / transfer-encoding / connection:
#     hop-by-hop or body-framing headers — we hand back a re-materialized body,
#     so Starlette recomputes the length and framing.
#   - accept-ranges / content-range: this proxy always does a plain GET and
#     returns the full body; it does NOT implement byte ranges. Forwarding the
#     upstream ``Accept-Ranges: bytes`` would advertise a capability we lack, and
#     uv's lazy-wheel reader trusts it — HEADing the wheel and then Range-reading
#     the ZIP's end-of-central-directory to pull METADATA without a full download.
#     Since the range never takes effect it reads garbage and fails with
#     "unable to locate the end of central directory record". Stripping these
#     forces clients to a normal full GET (our wheels are tiny, so the lazy-wheel
#     optimization buys nothing here).
_EXCLUDED_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "accept-ranges",
    "content-range",
}


@router.get("/simple/", response_class=HTMLResponse, include_in_schema=False)
async def list_packages(request: Request) -> Response:
    """List every package in the index (PEP 503 root).

    CodeArtifact does not serve the optional root listing, so for a CodeArtifact
    index we synthesize it from the control-plane API. Other indexes (devpi)
    serve their own root, so those are proxied unchanged.
    """
    settings = get_settings()
    if index_is_codeartifact(settings):
        try:
            names = await run_in_threadpool(list_codeartifact_packages, settings)
        except RuntimeError as e:  # incomplete CodeArtifact config
            logger.error("Cannot list packages: %s", e)
            raise HTTPException(status_code=502, detail="Package index not available") from e
        except Exception as e:  # boto/network — don't leak internals to the client
            logger.exception("CodeArtifact list_packages failed")
            raise HTTPException(status_code=502, detail="Package index not available") from e
        return HTMLResponse(_render_root_index(names))
    return await _proxy_to_index(request)


def _normalize_pep503(name: str) -> str:
    """PEP 503 name normalization (also the shape of the /simple/<name>/ href)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _render_root_index(names: list[str]) -> str:
    """Render a PEP 503 root index page from a list of package names."""
    links = "\n".join(
        f'    <a href="{n}/">{n}</a><br/>'
        for n in sorted({_normalize_pep503(html.escape(x)) for x in names})
    )
    return (
        "<!DOCTYPE html>\n<html>\n  <head><title>Simple Index</title></head>\n"
        f"  <body>\n{links}\n  </body>\n</html>\n"
    )


@router.get("/simple/{package_name}/", response_class=HTMLResponse, include_in_schema=False)
async def list_package_versions(request: Request, package_name: str) -> HTMLResponse:
    """Proxy: list versions of a package from the underlying index.

    Rewrites href links from /packages/<file> to /simple/<pkg>/<file> so that
    clients (uv/pip) stay on the gateway for the actual download.
    """
    resp = await _proxy_to_index(request)
    # Only rewrite HTML index pages (text/html), not JSON error responses.
    if not (resp.media_type or "").startswith("text/html") or resp.status_code != 200:
        return resp
    body = resp.body.decode("utf-8", errors="replace")
    # pypiserver-style links:  <a href="/packages/<file>…">
    body = re.sub(
        r'href="/packages/([^"]+)"',
        rf'href="/simple/{package_name}/\1"',
        body,
    )
    return HTMLResponse(body)


# {filename:path} — not {filename} — because CodeArtifact lists wheels under a
# version subdirectory (href "0.1.0/pkg-0.1.0-...whl"), so the download URL has
# an extra path segment. A plain {filename} matches only one segment and 404s
# before the request ever reaches the index. _proxy_to_index rebuilds the target
# from request.url.path, so it forwards the full sub-path unchanged.
@router.api_route(
    "/simple/{package_name}/{filename:path}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
async def download_wheel_simple(request: Request, package_name: str, filename: str) -> Response:
    """Proxy: download a wheel from the underlying index.

    pypiserver serves files at /packages/<file>, not /simple/<pkg>/<file>, so
    we rewrite the path before proxying.
    """
    settings = get_settings()
    index_url = settings.package_index_url
    if not index_url:
        raise HTTPException(status_code=503, detail="Package index not configured")

    if index_is_codeartifact(settings):
        # CodeArtifact serves the wheel at the same /simple/<pkg>/<version>/<file>
        # path it advertised in the index listing, so proxy the request unchanged
        # (with CodeArtifact token auth + redirect rewriting). The /packages/<file>
        # rewrite below is pypiserver-only and 404s against CodeArtifact.
        return await _proxy_to_index(request)

    base = index_url.rstrip("/")
    if base.endswith("/simple"):
        base = base[: -len("/simple")]
    target_url = f"{base}/packages/{filename}"

    headers = {}
    try:
        creds = resolve_index_read_credentials(settings)
    except RuntimeError as e:
        logger.error("Package index auth failed: %s", e)
        raise HTTPException(status_code=502, detail="Package index auth failed") from e
    if creds:
        user, password = creds
        credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(target_url, headers=headers, timeout=30.0)
        except httpx.HTTPError as e:
            logger.error("Index proxy request failed: %s — %s", target_url, e)
            raise HTTPException(status_code=502, detail="Package index unavailable") from e

    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _EXCLUDED_HEADERS}
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
    )


async def _proxy_to_index(request: Request) -> Response:
    """Forward request to the underlying package index with server credentials.

    Rewrites the request URL from /simple/* to the index URL and injects
    authentication headers.
    """
    settings = get_settings()
    index_url = settings.package_index_url
    if not index_url:
        raise HTTPException(status_code=503, detail="Package index not configured")

    # Build target URL: /simple/... → {index_url}/...
    path = request.url.path
    relative_path = path[len("/simple/"):] if path.startswith("/simple/") else path.lstrip("/")

    base = index_url.rstrip("/")
    target_url = f"{base}/{relative_path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # For CodeArtifact this mints (and caches) a fresh token — the static
    # package_index_user/password are only for devpi, so without this a
    # CodeArtifact-backed index answers every proxied read 401.
    headers = {}
    try:
        creds = resolve_index_read_credentials(settings)
    except RuntimeError as e:
        logger.error("Package index auth failed: %s", e)
        raise HTTPException(status_code=502, detail="Package index auth failed") from e
    if creds:
        user, password = creds
        credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(target_url, headers=headers, timeout=30.0)
        except httpx.HTTPError as e:
            logger.error("Index proxy request failed: %s — %s", target_url, e)
            raise HTTPException(status_code=502, detail="Package index unavailable") from e

    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _EXCLUDED_HEADERS}

    # Rewrite a redirect back onto /simple/. CodeArtifact 301s a non-normalized
    # name to its own canonical URL; forwarded verbatim that would leak the
    # backend host and point the client somewhere it can't authenticate. The
    # client reaches /simple/ on the gateway, which forwards here, so a relative
    # /simple/ Location keeps it on the gateway.
    for k in list(resp_headers):
        if k.lower() == "location" and resp_headers[k].startswith(base):
            resp_headers[k] = "/simple/" + resp_headers[k][len(base):].lstrip("/")

    content_type = resp.headers.get("content-type", "text/html")
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=content_type,
    )
