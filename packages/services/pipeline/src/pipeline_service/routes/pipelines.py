"""Pipeline definition routes — CRUD, search."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.database.postgres import get_async_session
from core.models.common import PaginatedResponse, TokenPayload
from core.models.pipeline import Pipeline
from core.schemas.pipeline import (
    PipelineCreate,
    PipelineForkRequest,
    PipelineResponse,
    PipelineUpdate,
    PipelineWithVersions,
)
from core.utils import is_uuid
from pipeline_service.crud.pipelines import (
    create_pipeline,
    delete_pipeline,
    fork_pipeline,
    get_pipeline,
    get_pipeline_by_slug,
    list_pipelines,
    update_pipeline,
)
from pipeline_service.crud.versions import serialize_pipeline_versions
from pipeline_service.events import publish_pipeline_created, publish_pipeline_updated

router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    """Extract org_id from token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


@router.post("", response_model=PipelineResponse, status_code=201)
async def create_pipeline_endpoint(
    data: PipelineCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "create", "*")),
) -> PipelineResponse:
    """Create a new pipeline definition."""
    org_id = _require_org(current_user)
    p = await create_pipeline(session, data, org_id=org_id, user_id=current_user.sub)
    resp = PipelineResponse.model_validate(p)
    await publish_pipeline_created(
        pipeline_id=p.id,
        pipeline_name=p.name,
        pipeline_slug=p.slug,
        org_id=org_id,
        user_id=current_user.sub,
    )
    return resp


@router.get("", response_model=PaginatedResponse)
async def list_pipelines_endpoint(
    q: str | None = None,
    is_public: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "read", "own")),
) -> PaginatedResponse:
    """List pipeline definitions."""
    scope_filters = build_scope_filters(current_user, Pipeline, "pipeline")
    items, total = await list_pipelines(
        session,
        q=q,
        is_public=is_public,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
    )
    return PaginatedResponse(
        items=[PipelineResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{identifier}", response_model=PipelineWithVersions)
async def get_pipeline_endpoint(
    identifier: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "read", "own")),
) -> PipelineWithVersions:
    """Get a pipeline definition with its version history. Accepts UUID or slug."""
    if is_uuid(identifier):
        p = await get_pipeline(session, identifier)
    else:
        _obj = await get_pipeline_by_slug(session, identifier)
        if _obj is None:
            raise HTTPException(status_code=404, detail=f"Pipeline '{identifier}' not found")
        p = _obj
    check_resource_access(current_user, p, resource_name="pipeline")
    base = PipelineResponse.model_validate(p)
    return PipelineWithVersions(
        **base.model_dump(),
        versions=await serialize_pipeline_versions(session, list(p.versions), pipeline=p),
    )


@router.patch("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline_endpoint(
    pipeline_id: str,
    data: PipelineUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "update", "own")),
) -> PipelineResponse:
    """Update pipeline metadata (name, description, tags, is_public)."""
    p = await get_pipeline(session, pipeline_id)
    check_resource_access(current_user, p, resource_name="pipeline", write=True)
    p = await update_pipeline(session, pipeline_id, data, user_id=current_user.sub)
    resp = PipelineResponse.model_validate(p)
    await publish_pipeline_updated(
        pipeline_id=p.id,
        pipeline_name=p.name,
        version=p.version,
    )
    return resp


@router.post("/{pipeline_id}/fork", response_model=PipelineResponse, status_code=201)
async def fork_pipeline_endpoint(
    pipeline_id: str,
    data: PipelineForkRequest,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "create", "*")),
) -> PipelineResponse:
    """Fork a pipeline to evolve its topology while keeping lineage."""
    org_id = _require_org(current_user)
    src = await get_pipeline(session, pipeline_id)
    check_resource_access(current_user, src, resource_name="pipeline")
    fork = await fork_pipeline(session, pipeline_id, data, org_id=org_id, user_id=current_user.sub)
    resp = PipelineResponse.model_validate(fork)
    await publish_pipeline_created(
        pipeline_id=fork.id,
        pipeline_name=fork.name,
        pipeline_slug=fork.slug,
        org_id=org_id,
        user_id=current_user.sub,
    )
    return resp


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline_endpoint(
    pipeline_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("pipeline", "delete", "own")),
) -> None:
    """Delete a pipeline definition and all its runs."""
    p = await get_pipeline(session, pipeline_id)
    check_resource_access(current_user, p, resource_name="pipeline", write=True)
    await delete_pipeline(session, pipeline_id)
