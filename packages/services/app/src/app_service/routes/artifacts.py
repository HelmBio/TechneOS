"""Artifact publishing — app-service owns this for the whole platform.

app-service is the single artifact publisher: it holds the docker socket (image
push) and the registry/CodeArtifact credentials (wheel publish, plus the
``/simple/`` read proxy in :mod:`app_service.routes.simple`). The gateway proxies
``/api/v1/artifacts/*`` and ``/simple/*`` here. See :mod:`app_service.images`
and :mod:`app_service.publish`.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from app_service.images import publish_image_to_registry
from app_service.publish import publish_wheel_to_index
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.config import get_settings
from core.models.common import TokenPayload
from core.schemas.artifact import ArtifactRegister, ArtifactResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/image", response_model=ArtifactResponse, status_code=201, tags=["artifacts"])
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    slug: str = Form(...),
    version: str = Form(...),
    origin: str = Form(...),
    source_commit_sha: str | None = Form(None),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("compute_artifact", "create", "*")),
) -> ArtifactResponse:
    """Upload a docker image tar, push it to the registry, record in inventory.

    The client only uploads the ``docker save`` tar; app-service (which holds the
    docker socket) handles the load + registry push and records the artifact.
    """
    if not file.filename or not file.filename.endswith(".tar"):
        raise HTTPException(status_code=400, detail="File must be a .tar file (docker save output)")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # docker SDK + boto3 calls are blocking — run off the event loop.
        image_ref = await run_in_threadpool(publish_image_to_registry, tmp_path, slug, version)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Image push failed: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    return await _record_artifact(
        ArtifactRegister(
            kind="docker_image",
            origin=origin,
            name=f"techneos/{slug}",
            version=version,
            registry_url=image_ref,
            size_bytes=len(content),
            source_commit_sha=source_commit_sha,
        ),
        request.headers.get("authorization"),
    )


def _normalize_package_name(name: str) -> str:
    """PEP 503 normalisation: lowercase, runs of ``-_.`` collapsed to ``-``.

    Makes the wheel-filename distribution (``chembl_agent``) match the project
    name the inventory is keyed by and the tool/agent validation looks up
    (``chembl-agent``).
    """
    return re.sub(r"[-_.]+", "-", name).lower()


@router.post("/wheel", response_model=ArtifactResponse, status_code=201, tags=["artifacts"])
async def upload_wheel(
    request: Request,
    file: UploadFile = File(...),
    origin: str = Form(...),
    entry_point: str | None = Form(None),
    source_commit_sha: str | None = Form(None),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("compute_artifact", "create", "*")),
) -> ArtifactResponse:
    """Upload a wheel, publish it to the index, record in inventory.

    The client only uploads the .whl file; app-service holds the index
    credentials and publishes via ``uv publish``.
    """
    if not file.filename or not file.filename.endswith(".whl"):
        raise HTTPException(status_code=400, detail="File must be a .whl file")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Wheel filename: {distribution}-{version}(-{build})?-{py}-{abi}-{platform}.whl
    parts = file.filename.split("-")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid wheel filename format")
    # The distribution escapes the project name (runs of -_. → _), e.g.
    # ``chembl-agent`` → ``chembl_agent-0.1.0-...whl``. The inventory is keyed by
    # the PEP 503 name and the downstream tool/agent validation looks it up by
    # the project name — normalise or the recorded row won't match (422).
    package_name = _normalize_package_name(parts[0])
    version = parts[1]

    # Save with the original filename so uv publish recognises it.
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / file.filename
    tmp_path.write_bytes(content)
    try:
        # uv publish is blocking — run off the event loop.
        publish_url = await run_in_threadpool(publish_wheel_to_index, tmp_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Publish failed: {e}") from e
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return await _record_artifact(
        ArtifactRegister(
            kind="wheel",
            origin=origin,
            name=package_name,
            version=version,
            registry_url=publish_url,
            size_bytes=len(content),
            source_commit_sha=source_commit_sha,
            metadata={"entry_point": entry_point} if entry_point else {},
        ),
        request.headers.get("authorization"),
    )


async def _record_artifact(register: ArtifactRegister, auth_header: str | None) -> ArtifactResponse:
    """Record a published artifact in the inventory via the tool-service.

    The tool-service owns the ``compute_artifacts`` table; forwarding the caller's
    bearer token runs the idempotent upsert as the same user. The artifact is
    already published/pushed, so a recording failure surfaces as a 502; the
    downstream version/definition create is hard-validated against the inventory.
    """
    settings = get_settings()
    url = f"{settings.tool_service_url}{settings.api_v1_prefix}/compute-artifacts"
    headers = {"Authorization": auth_header} if auth_header else {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, json=register.model_dump(mode="json"), headers=headers, timeout=30.0
            )
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Artifact published but inventory recording failed: {e}",
        ) from e
    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=(
                f"Artifact published but inventory recording failed "
                f"(HTTP {resp.status_code}): {resp.text}"
            ),
        )
    body = resp.json()
    # ArtifactResponse validates ``metadata`` under the alias ``metadata_``; the
    # tool-service serialises it under the field name, so remap before re-validating.
    if "metadata" in body:
        body["metadata_"] = body["metadata"]
    return ArtifactResponse.model_validate(body)
