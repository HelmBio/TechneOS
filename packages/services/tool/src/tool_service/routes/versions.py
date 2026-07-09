"""Tool version routes — create, list, update, delete, replace content."""
from contextlib import suppress
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import check_resource_access
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from core.schemas.tool import (
    RuntimeValidationRequest,
    RuntimeValidationResponse,
    ToolVersionContentReplace,
    ToolVersionCreate,
    ToolVersionResponse,
    ToolVersionUpdate,
)
from tool_service.crud.tools import get_tool
from tool_service.crud.versions import (
    create_tool_version,
    delete_tool_version,
    get_tool_version,
    list_tool_versions,
    replace_tool_version_content,
    serialize_tool_versions,
    tool_version_has_runs,
    update_tool_version,
)
from tool_service.events import publish_tool_version_active, publish_tool_version_deleted
from tool_service.validation import (
    run_package_validation,
    validate_version_content,
    validate_version_create,
)

router = APIRouter()


@router.post("", response_model=ToolVersionResponse, status_code=201)
async def create_version_endpoint(
    tool_id: str,
    data: ToolVersionCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "create", "own")),
) -> ToolVersionResponse:
    """Create a new version for a tool."""
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool")
    validate_version_create(t.tool_type, data)
    v = await create_tool_version(session, tool_id, data, user_id=current_user.sub)
    response = ToolVersionResponse.model_validate(v)
    if v.status == "active":
        with suppress(Exception):
            await publish_tool_version_active(
                tool_id=tool_id,
                tool_slug=t.slug,
                tool_name=t.name,
                version=v.version,
            )
    return response


@router.get("", response_model=list[ToolVersionResponse])
async def list_versions_endpoint(
    tool_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "read", "own")),
) -> list[ToolVersionResponse]:
    """List all versions of a tool."""
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool")
    versions = await list_tool_versions(session, tool_id)
    return await serialize_tool_versions(session, versions)


@router.get("/{version_id}", response_model=ToolVersionResponse)
async def get_version_endpoint(
    tool_id: str,
    version_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "read", "own")),
) -> ToolVersionResponse:
    """Get a specific tool version."""
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool")
    v = await get_tool_version(session, version_id)
    resp = ToolVersionResponse.model_validate(v)
    resp.has_runs = await tool_version_has_runs(session, version_id)
    return resp


@router.patch("/{version_id}", response_model=ToolVersionResponse)
async def update_version_endpoint(
    tool_id: str,
    version_id: str,
    data: ToolVersionUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "update", "own")),
) -> ToolVersionResponse:
    """Update a tool version's metadata (status, readme, docs, etc.).

    Content fields (docker image, scripts, schemas) must be updated
    via the PUT /{version_id}/content endpoint instead.
    """
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool", write=True)
    v = await update_tool_version(session, version_id, data, user_id=current_user.sub)
    resp = ToolVersionResponse.model_validate(v)
    resp.has_runs = await tool_version_has_runs(session, version_id)
    return resp


@router.put("/{version_id}/content", response_model=ToolVersionResponse)
async def replace_version_content_endpoint(
    tool_id: str,
    version_id: str,
    data: ToolVersionContentReplace,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "update", "own")),
) -> ToolVersionResponse:
    """Replace a tool version's functional content.

    Resets version status to 'draft' since content changed.
    Use PATCH to update metadata fields like status, readme, docs.
    """
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool", write=True)
    validate_version_content(t.tool_type, data)
    v = await replace_tool_version_content(session, version_id, data, user_id=current_user.sub)
    return ToolVersionResponse.model_validate(v)


@router.post("/validate", response_model=RuntimeValidationResponse)
async def validate_version_content_endpoint(
    tool_id: str,
    data: RuntimeValidationRequest,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "read", "own")),
) -> RuntimeValidationResponse:
    """Validate a pypi tool by pip-installing it in a sandbox and calling
    its entry point (or running the supplied test_script if any).

    Module-type validation is not supported; pypi is the only validatable
    runtime."""
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool")
    if t.tool_type != "pypi":
        raise HTTPException(
            status_code=422,
            detail="Only pypi-type tools support runtime validation",
        )

    if not all([data.package_name, data.package_version, data.entry_point]):
        raise HTTPException(status_code=422, detail="Package fields required for pypi validation")
    return await run_package_validation(
        package_name=cast(str, data.package_name),
        package_version=cast(str, data.package_version),
        entry_point=cast(str, data.entry_point),
        package_index_url=data.package_index_url,
        test_script=data.test_script,
    )


@router.delete("/{version_id}", status_code=204)
async def delete_version_endpoint(
    tool_id: str,
    version_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("tool", "delete", "org")),
) -> None:
    """Delete a specific tool version. Only org_admin or platform_admin."""
    t = await get_tool(session, tool_id)
    check_resource_access(current_user, t, resource_name="tool", write=True)
    v = await get_tool_version(session, version_id)
    await delete_tool_version(session, version_id)
    with suppress(Exception):
        await publish_tool_version_deleted(
            tool_id=tool_id,
            tool_slug=t.slug,
            tool_name=t.name,
            version=v.version,
        )
