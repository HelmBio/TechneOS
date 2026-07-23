"""Artifact upload and package index proxy routes.

Provides endpoints for:
- Uploading wheels and docker images (gateway publishes to index/registry)
- Proxying PyPI Simple API requests to the underlying index

Clients never connect directly to the index or registry — the gateway
is the single entry point for all package operations.
"""

from __future__ import annotations

import html
import io
import logging
import re
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.config import get_settings
from core.models.common import TokenPayload
from core.schemas.artifact import ArtifactResponse
from gateway.publish import (
    index_is_codeartifact,
    list_codeartifact_packages,
    publish_wheel_to_index,
    push_image_to_registry,
    resolve_index_read_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Upload endpoints (auth required) ────────────────────────────────────────


@router.post(
    "/api/v1/artifacts/wheel",
    response_model=ArtifactResponse,
    status_code=201,
    tags=["artifacts"],
)
async def upload_wheel(
    file: UploadFile = File(...),
    origin: str = Form(...),
    entry_point: str | None = Form(None),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("compute_artifact", "create", "*")),
) -> ArtifactResponse:
    """Upload a wheel, publish to the underlying index, record in inventory.

    The gateway handles index authentication and publish. The client only
    needs to upload the .whl file.
    """
    # Validate file is a wheel
    if not file.filename or not file.filename.endswith(".whl"):
        raise HTTPException(status_code=400, detail="File must be a .whl file")

    # Read file content
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Parse wheel filename to get package name and version
    # Format: {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
    parts = file.filename.split("-")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid wheel filename format")
    package_name = parts[0]
    version = parts[1]

    # Save to temp file and publish
    with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        publish_url = publish_wheel_to_index(tmp_path)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Publish failed: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

    # Record artifact in inventory (via tool-service)
    # TODO: Call tool-service to record artifact
    # For now, return a placeholder response
    return ArtifactResponse(
        id="",  # Will be set by tool-service
        kind="wheel",
        origin=origin,
        name=package_name,
        version=version,
        registry_url=publish_url,
        status="available",
        metadata={"entry_point": entry_point} if entry_point else {},
    )


@router.post(
    "/api/v1/artifacts/image",
    response_model=ArtifactResponse,
    status_code=201,
    tags=["artifacts"],
)
async def upload_image(
    file: UploadFile = File(...),
    slug: str = Form(...),
    version: str = Form(...),
    origin: str = Form(...),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("compute_artifact", "create", "*")),
) -> ArtifactResponse:
    """Upload a docker image tar, push to registry, record in inventory.

    The gateway handles registry authentication and push. The client only
    needs to upload the .tar file (output of ``docker save``).
    """
    # Validate file is a tar
    if not file.filename or not file.filename.endswith(".tar"):
        raise HTTPException(status_code=400, detail="File must be a .tar file (docker save output)")

    # Read file content
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Save to temp file and push
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        image_ref = push_image_to_registry(tmp_path, slug, version)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Push failed: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

    # Record artifact in inventory (via tool-service)
    # TODO: Call tool-service to record artifact
    # For now, return a placeholder response
    return ArtifactResponse(
        id="",  # Will be set by tool-service
        kind="docker_image",
        origin=origin,
        name=f"techneos/{slug}",
        version=version,
        registry_url=image_ref,
        status="available",
    )


# ── PyPI Simple API proxy (public — for uv/pip resolution) ──────────────────


@router.get("/simple/", response_class=HTMLResponse, include_in_schema=False)
async def list_packages(request: Request) -> Response:
    """List every package in the index (PEP 503 root).

    CodeArtifact does not serve the optional root listing, so for a CodeArtifact
    index we synthesize it from the control-plane API (list_packages). Other
    indexes (devpi) serve their own root, so those are proxied unchanged.
    """
    settings = get_settings()
    if index_is_codeartifact(settings):
        try:
            names = await run_in_threadpool(list_codeartifact_packages, settings)
        except RuntimeError as e:  # incomplete CodeArtifact config
            logger.error("Cannot list packages: %s", e)
            raise HTTPException(status_code=502, detail="Package index not available")
        except Exception:  # boto/network — don't leak internals to the client
            logger.exception("CodeArtifact list_packages failed")
            raise HTTPException(status_code=502, detail="Package index not available")
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
    """Proxy: list versions of a package from the underlying index."""
    return await _proxy_to_index(request)


# {filename:path} — not {filename} — because CodeArtifact lists wheels under a
# version subdirectory (href "0.1.0/pkg-0.1.0-...whl"), so the download URL has
# an extra path segment. A plain {filename} matches only one segment and 404s
# before the request ever reaches the index. _proxy_to_index rebuilds the target
# from request.url.path, so it forwards the full sub-path unchanged.
@router.get("/simple/{package_name}/{filename:path}", include_in_schema=False)
async def download_wheel_simple(request: Request, package_name: str, filename: str) -> Response:
    """Proxy: download a wheel from the underlying index."""
    return await _proxy_to_index(request)


async def _proxy_to_index(request: Request) -> Response:
    """Forward request to the underlying package index with gateway credentials.

    Rewrites the request URL from /simple/* to the index URL and injects
    authentication headers.
    """
    settings = get_settings()
    index_url = settings.package_index_url

    if not index_url:
        raise HTTPException(status_code=503, detail="Package index not configured")

    # Build target URL: /simple/... → {index_url}/...
    # index_url typically ends with /simple/ or similar
    path = request.url.path
    # Remove /simple/ prefix and append to index URL
    if path.startswith("/simple/"):
        relative_path = path[len("/simple/"):]
    else:
        relative_path = path.lstrip("/")

    # Ensure index_url ends with / and relative_path doesn't start with /
    base = index_url.rstrip("/")
    target_url = f"{base}/{relative_path}"

    # Preserve query parameters
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Build headers with auth. For CodeArtifact this mints (and caches) a fresh
    # token — the static package_index_user/password are only for devpi, so
    # without this a CodeArtifact-backed index answers every proxied read 401.
    headers = {}
    try:
        creds = resolve_index_read_credentials(settings)
    except RuntimeError as e:
        logger.error("Package index auth failed: %s", e)
        raise HTTPException(status_code=502, detail="Package index auth failed")
    if creds:
        import base64
        user, password = creds
        credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"

    # Proxy request
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                target_url,
                headers=headers,
                timeout=30.0,
            )
        except httpx.HTTPError as e:
            logger.error("Index proxy request failed: %s — %s", target_url, e)
            raise HTTPException(status_code=502, detail="Package index unavailable")

    # Filter headers that shouldn't be forwarded
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}

    # Rewrite a redirect back onto the gateway. CodeArtifact 301s a non-normalized
    # name to its own canonical URL; forwarded verbatim that would leak the backend
    # host and point the client somewhere it can't authenticate. Map the index base
    # back to /simple/ so the client stays on us.
    for k in list(resp_headers):
        if k.lower() == "location" and resp_headers[k].startswith(base):
            resp_headers[k] = "/simple/" + resp_headers[k][len(base):].lstrip("/")

    # Determine content type
    content_type = resp.headers.get("content-type", "text/html")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=content_type,
    )
