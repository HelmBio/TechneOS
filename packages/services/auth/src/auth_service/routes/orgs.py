"""Organization management routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.crud.orgs import count_orgs, create_org, get_org_by_id, list_orgs, update_org
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.exceptions import NotFoundError
from core.models.common import OrgCreate, OrgResponse, OrgUpdate, PaginatedResponse, TokenPayload

router = APIRouter()


@router.post("", response_model=OrgResponse, status_code=201)
async def create_org_route(
    data: OrgCreate,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("org", "create", "platform")),
) -> OrgResponse:
    """Create a new organization (platform admin only)."""
    org = await create_org(session, data)
    return OrgResponse.model_validate(org)


@router.get("", response_model=PaginatedResponse)
async def list_orgs_route(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> PaginatedResponse:
    """List organizations."""
    orgs = await list_orgs(session, skip=skip, limit=limit)
    total = await count_orgs(session)
    return PaginatedResponse(
        items=[OrgResponse.model_validate(o) for o in orgs],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org_route(
    org_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> OrgResponse:
    """Get an organization by ID."""
    org = await get_org_by_id(session, org_id)
    if org is None:
        raise NotFoundError("Organization", org_id)
    return OrgResponse.model_validate(org)


@router.put("/{org_id}", response_model=OrgResponse)
async def update_org_route(
    org_id: str,
    data: OrgUpdate,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("org", "update", "org")),
) -> OrgResponse:
    """Update an organization."""
    org = await update_org(session, org_id, data)
    return OrgResponse.model_validate(org)
