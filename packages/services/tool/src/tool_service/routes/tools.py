"""Tool routes — CRUD, search, listing."""

from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.database.postgres import get_async_session
from core.models.common import PaginatedResponse, TokenPayload
from core.models.tool import Tool
from core.schemas.tool import ToolCreate, ToolResponse, ToolUpdate, ToolWithVersions
from core.utils import is_uuid
from tool_service.crud.tools import (
    create_tool,
    delete_tool,
    get_tool,
    get_tool_by_slug,
    list_tools,
    update_tool,
)
from tool_service.crud.versions import list_tool_versions, serialize_tool_versions
from tool_service.events import publish_tool_created

router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    """Extract org_id from token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


@router.post("", response_model=ToolResponse, status_code=201)
async def create_tool_endpoint(
    data: ToolCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "create", "*")),
) -> ToolResponse:
    """Register a new tool."""
    org_id = _require_org(current_user)
    t = await create_tool(session, data, org_id=org_id, user_id=current_user.sub)
    response = ToolResponse.model_validate(t)
    # Fire event (non-blocking — don't fail the request if notification fails)
    with suppress(Exception):
        await publish_tool_created(tool_id=t.id, tool_slug=t.slug, tool_name=t.name)
    return response


@router.get("", response_model=PaginatedResponse)
async def list_tools_endpoint(
    q: str | None = None,
    category: str | None = None,
    tool_type: str | None = None,
    is_public: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "read", "own")),
) -> PaginatedResponse:
    """Search / list tools."""
    scope_filters = build_scope_filters(current_user, Tool, "tool")
    items, total = await list_tools(
        session,
        q=q,
        category=category,
        tool_type=tool_type,
        is_public=is_public,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
    )
    return PaginatedResponse(
        items=[ToolResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/by-slug/{slug}", response_model=ToolWithVersions)
async def get_tool_by_slug_endpoint(
    slug: str,
    session: AsyncSession = Depends(get_async_session),
) -> ToolWithVersions:
    """Get a tool by slug with all its versions (internal/service-to-service)."""
    t = await get_tool_by_slug(session, slug)
    if t is None:
        raise HTTPException(status_code=404, detail=f"Tool with slug '{slug}' not found")
    versions = await list_tool_versions(session, t.id)
    base = ToolResponse.model_validate(t)
    return ToolWithVersions(
        **base.model_dump(),
        versions=await serialize_tool_versions(session, versions),
    )


@router.get("/{identifier}", response_model=ToolWithVersions)
async def get_tool_endpoint(
    identifier: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "read", "own")),
) -> ToolWithVersions:
    """Get a tool with all its versions. Accepts UUID or slug."""
    if is_uuid(identifier):
        t = await get_tool(session, identifier)
    else:
        _obj = await get_tool_by_slug(session, identifier)
        if _obj is None:
            raise HTTPException(status_code=404, detail=f"Tool '{identifier}' not found")
        t = _obj
    check_resource_access(current_user, t, resource_name="tool")
    versions = await list_tool_versions(session, t.id)
    base = ToolResponse.model_validate(t)
    return ToolWithVersions(
        **base.model_dump(),
        versions=await serialize_tool_versions(session, versions),
    )


@router.patch("/{tool_id}", response_model=ToolResponse)
async def update_tool_endpoint(
    tool_id: str,
    data: ToolUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "update", "own")),
) -> ToolResponse:
    """Update tool metadata."""
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool", write=True)
    t = await update_tool(session, tool_id, data, user_id=current_user.sub)
    return ToolResponse.model_validate(t)


@router.delete("/{tool_id}", status_code=204)
async def delete_tool_endpoint(
    tool_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "delete", "org")),
) -> None:
    """Delete a tool and all its versions. Only org_admin or platform_admin."""
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool", write=True)
    await delete_tool(session, tool_id)
