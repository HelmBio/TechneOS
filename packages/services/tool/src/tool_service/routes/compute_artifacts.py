"""Compute artifact inventory routes — list, get, register (upsert), update, delete.

The inventory records every built & published wheel / docker image. Build
scripts call ``POST`` after publishing; the admin portal reads it to power
artifact pickers and validation in the tool-version editor.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from core.schemas.artifact import ArtifactRegister, ArtifactResponse, ArtifactUpdate
from tool_service.crud.artifacts import (
    delete_artifact,
    get_artifact,
    list_artifacts,
    register_artifact,
    update_artifact,
)

router = APIRouter()


@router.get("", response_model=list[ArtifactResponse])
async def list_artifacts_endpoint(
    kind: str | None = None,
    origin: str | None = None,
    status: str | None = None,
    name: str | None = None,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ArtifactResponse]:
    artifacts = await list_artifacts(
        session, kind=kind, origin=origin, status=status, name=name
    )
    return [ArtifactResponse.model_validate(a) for a in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact_endpoint(
    artifact_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ArtifactResponse:
    artifact = await get_artifact(session, artifact_id)
    return ArtifactResponse.model_validate(artifact)


@router.post("", response_model=ArtifactResponse, status_code=201)
async def register_artifact_endpoint(
    data: ArtifactRegister,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("compute_artifact", "create", "*")),
) -> ArtifactResponse:
    artifact = await register_artifact(session, data, user_id=current_user.sub)
    return ArtifactResponse.model_validate(artifact)


@router.patch("/{artifact_id}", response_model=ArtifactResponse)
async def update_artifact_endpoint(
    artifact_id: str,
    data: ArtifactUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("compute_artifact", "update", "*")),
) -> ArtifactResponse:
    artifact = await update_artifact(session, artifact_id, data)
    return ArtifactResponse.model_validate(artifact)


@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact_endpoint(
    artifact_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("compute_artifact", "delete", "*")),
) -> None:
    await delete_artifact(session, artifact_id)
