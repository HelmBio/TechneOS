"""User management routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.crud.admin import write_audit_log
from core.audit import client_ip as _client_ip
from auth_service.crud.users import (
    count_users,
    create_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    update_user,
)
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.database.postgres import get_async_session
from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.common import (
    AuditLogResponse,
    PaginatedResponse,
    RoleResponse,
    TokenPayload,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from core.models.user import AuditLog, Role, User

router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    """Extract org_id from the token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="Organization membership required")
    return current_user.org_id


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles_for_org(
    session: AsyncSession = Depends(get_async_session),
    _user: TokenPayload = Depends(get_current_user),
) -> list[RoleResponse]:
    """List all available roles (any authenticated user)."""
    result = await session.execute(select(Role).order_by(Role.name))
    roles = list(result.scalars().all())
    return [RoleResponse.model_validate(r) for r in roles]


@router.get("/audit-logs", response_model=PaginatedResponse)
async def list_org_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    action: str | None = None,
    resource_type: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("user", "read", "org")),
) -> PaginatedResponse:
    """List audit logs scoped to the current user's organization.

    Returns only log entries created by users that belong to the same org.
    Platform admins can see all logs (use the admin endpoint instead).
    """
    # Get user IDs in the caller's org
    org_id = _require_org(current_user)
    user_ids_stmt = select(User.id).where(User.org_id == org_id)

    # Build audit log query scoped to those users
    stmt = (
        select(AuditLog)
        .where(AuditLog.user_id.in_(user_ids_stmt))
        .offset(skip)
        .limit(limit)
        .order_by(AuditLog.timestamp.desc())
    )
    count_stmt = select(func.count(AuditLog.id)).where(AuditLog.user_id.in_(user_ids_stmt))

    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
        count_stmt = count_stmt.where(AuditLog.resource_type == resource_type)

    result = await session.execute(stmt)
    logs = list(result.scalars().all())
    total = (await session.execute(count_stmt)).scalar_one()

    return PaginatedResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user_route(
    data: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("user", "update", "org")),
) -> User:
    """Create a new local user within the caller's organization."""
    org_id = current_user.org_id
    if not org_id:
        raise HTTPException(status_code=403, detail="Organization membership required")

    data.org_id = org_id

    existing = await get_user_by_email(session, data.email)
    if existing is not None:
        raise AlreadyExistsError("User", data.email)

    user = await create_user(session, data)

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="create_user",
        resource_type="user",
        resource_id=user.id,
        details={"email": data.email, "full_name": data.full_name, "org_id": org_id},
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    await session.commit()
    return user


@router.get("", response_model=PaginatedResponse)
async def list_users_route(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    org_id: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("user", "read", "org")),
) -> PaginatedResponse:
    """List users (requires org-level read access)."""
    # Scope to the user's org unless they are a platform admin
    effective_org_id = org_id if current_user.role == "platform_admin" else current_user.org_id
    users = await list_users(session, skip=skip, limit=limit, org_id=effective_org_id)
    total = await count_users(session, org_id=effective_org_id)
    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_route(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
) -> UserResponse:
    """Get a user by ID (scoped to caller's org)."""
    org_id = _require_org(current_user)
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    # Enforce org scoping — non-admins can only view users in their own org
    if current_user.role != "platform_admin" and user.org_id != org_id:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user_route(
    user_id: str,
    data: UserUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_user),
    _perm: bool = Depends(require_permission("user", "update", "org")),
) -> UserResponse:
    """Update a user (scoped to caller's org)."""
    org_id = _require_org(current_user)

    # Verify the target user belongs to the caller's org
    target_user = await get_user_by_id(session, user_id)
    if target_user is None:
        raise NotFoundError("User", user_id)
    if current_user.role != "platform_admin" and target_user.org_id != org_id:
        raise HTTPException(status_code=404, detail="User not found")

    user = await update_user(session, user_id, data)

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="update_user",
        resource_type="user",
        resource_id=user_id,
        details=data.model_dump(exclude_unset=True),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return UserResponse.model_validate(user)
