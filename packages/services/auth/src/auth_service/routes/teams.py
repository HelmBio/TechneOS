"""Team management routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.crud.admin import write_audit_log
from auth_service.crud.teams import (
    count_teams,
    create_team,
    get_team_by_id,
    list_teams,
    update_team,
)
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.exceptions import NotFoundError
from core.models.common import PaginatedResponse, TeamCreate, TeamResponse, TeamUpdate, TokenPayload

router = APIRouter()
# Flat router for /teams (lists / fetches teams scoped to the caller's org)
flat_router = APIRouter()


@flat_router.get("", response_model=PaginatedResponse)
async def list_org_teams_route(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> PaginatedResponse:
    """List teams in the current user's organization.

    Convenience flat endpoint — equivalent to ``GET /orgs/{org_id}/teams``
    but resolves ``org_id`` from the caller. Used by frontend pickers.
    """
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    teams = await list_teams(session, current_user.org_id, skip=skip, limit=limit)
    total = await count_teams(session, current_user.org_id)
    return PaginatedResponse(
        items=[TeamResponse.model_validate(t) for t in teams],
        total=total,
        skip=skip,
        limit=limit,
    )


@flat_router.get("/{team_id}", response_model=TeamResponse)
async def get_org_team_route(
    team_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> TeamResponse:
    """Get a team in the caller's org by ID."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    team = await get_team_by_id(session, team_id)
    if team is None or team.org_id != current_user.org_id:
        raise NotFoundError("Team", team_id)
    return TeamResponse.model_validate(team)


@router.post("", response_model=TeamResponse, status_code=201)
async def create_team_route(
    org_id: str,
    data: TeamCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("team", "create", "org")),
) -> TeamResponse:
    """Create a new team within an organization."""
    team = await create_team(session, org_id, data)

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="create_team",
        resource_type="team",
        resource_id=team.id,
        details={"name": data.name, "org_id": org_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return TeamResponse.model_validate(team)


@router.get("", response_model=PaginatedResponse)
async def list_teams_route(
    org_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> PaginatedResponse:
    """List teams within an organization."""
    teams = await list_teams(session, org_id, skip=skip, limit=limit)
    total = await count_teams(session, org_id)
    return PaginatedResponse(
        items=[TeamResponse.model_validate(t) for t in teams],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team_route(
    org_id: str,
    team_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> TeamResponse:
    """Get a team by ID."""
    team = await get_team_by_id(session, team_id)
    if team is None or team.org_id != org_id:
        raise NotFoundError("Team", team_id)
    return TeamResponse.model_validate(team)


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team_route(
    org_id: str,
    team_id: str,
    data: TeamUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("team", "update", "org")),
) -> TeamResponse:
    """Update a team."""
    team = await get_team_by_id(session, team_id)
    if team is None or team.org_id != org_id:
        raise NotFoundError("Team", team_id)
    updated = await update_team(session, team_id, data)

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="update_team",
        resource_type="team",
        resource_id=team_id,
        details=data.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return TeamResponse.model_validate(updated)
