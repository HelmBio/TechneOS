"""Pipeline version routes — create, list, update status."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from core.schemas.pipeline import (
    PipelineVersionCreate,
    PipelineVersionResponse,
    PipelineVersionUpdate,
)
from pipeline_service.crud.pipelines import get_pipeline
from pipeline_service.crud.versions import (
    create_pipeline_version,
    delete_pipeline_version,
    get_pipeline_version,
    list_pipeline_versions,
    serialize_pipeline_version,
    serialize_pipeline_versions,
    update_pipeline_version,
)

router = APIRouter()


@router.post("", response_model=PipelineVersionResponse, status_code=201)
async def create_version_endpoint(
    pipeline_id: str,
    data: PipelineVersionCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "update", "own")),
) -> PipelineVersionResponse:
    """Create a new version for a pipeline."""
    pipeline = await get_pipeline(session, pipeline_id)  # ensure pipeline exists
    v = await create_pipeline_version(session, pipeline_id, data, user_id=current_user.sub)

    # Publish event (best-effort, does not block response)
    from pipeline_service.events import publish_pipeline_version_created

    await publish_pipeline_version_created(
        pipeline_id=pipeline_id,
        pipeline_name=pipeline.name,
        pipeline_slug=pipeline.slug,
        version=v.version,
        changelog=data.changelog,
    )

    return await serialize_pipeline_version(session, v, pipeline=pipeline)


@router.get("", response_model=list[PipelineVersionResponse])
async def list_versions_endpoint(
    pipeline_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "read", "own")),
) -> list[PipelineVersionResponse]:
    """List all versions of a pipeline."""
    pipeline = await get_pipeline(session, pipeline_id)
    versions = await list_pipeline_versions(session, pipeline_id)
    return await serialize_pipeline_versions(session, versions, pipeline=pipeline)


@router.get("/{version_id}", response_model=PipelineVersionResponse)
async def get_version_endpoint(
    pipeline_id: str,
    version_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "read", "own")),
) -> PipelineVersionResponse:
    """Get a specific pipeline version."""
    v = await get_pipeline_version(session, version_id)
    pipeline = await get_pipeline(session, v.pipeline_id)
    return await serialize_pipeline_version(session, v, pipeline=pipeline)


@router.patch("/{version_id}", response_model=PipelineVersionResponse)
async def update_version_endpoint(
    pipeline_id: str,
    version_id: str,
    data: PipelineVersionUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "update", "own")),
) -> PipelineVersionResponse:
    """Update a pipeline version (status or bindings)."""
    v = await update_pipeline_version(session, version_id, data, user_id=current_user.sub)
    pipeline = await get_pipeline(session, v.pipeline_id)
    return await serialize_pipeline_version(session, v, pipeline=pipeline)


@router.delete("/{version_id}", status_code=204)
async def delete_version_endpoint(
    pipeline_id: str,
    version_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "update", "own")),
) -> None:
    """Delete a pipeline version and all its runs."""
    await delete_pipeline_version(session, version_id)
