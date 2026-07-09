"""Platform admin routes — stats, user management, audit logs, service health.

All routes require the ``platform_admin`` role.
"""

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth_service.crud.admin import (
    admin_delete_user,
    admin_reset_password,
    admin_update_user,
    check_services_health,
    count_audit_logs,
    create_llm_provider,
    create_org,
    create_role,
    delete_llm_provider,
    get_docker_container_logs,
    get_platform_stats,
    list_audit_logs,
    list_buckets,
    list_docker_containers,
    list_llm_providers,
    list_roles,
    read_service_logs,
    update_llm_provider,
    update_org,
    update_role,
    write_audit_log,
)
from auth_service.crud.buckets import create_bucket
from auth_service.crud.teams import count_all_teams, list_all_teams
from auth_service.crud.users import create_user, get_user_by_email, get_user_by_id
from core.auth.dependencies import get_current_admin_user, get_current_superuser
from core.database.postgres import get_async_session
from core.exceptions import NotFoundError
from core.models.bucket import ObjectStoreBucket
from core.models.common import (
    AdminResetPassword,
    AdminStatsResponse,
    AdminUserCreate,
    AdminUserUpdate,
    AuditLogResponse,
    DockerContainerLogsResponse,
    DockerContainerResponse,
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderUpdate,
    OrgCreate,
    OrgResponse,
    OrgUpdate,
    PaginatedResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    ServiceHealthResponse,
    ServiceLogsResponse,
    TeamResponse,
    TokenPayload,
    UserResponse,
)
from core.models.user import Org, User
from core.schemas.bucket import BucketCreate, BucketResponse

router = APIRouter()


# --- Dashboard stats ---


@router.get("/stats", response_model=AdminStatsResponse)
async def admin_stats(
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> AdminStatsResponse:
    """Platform-wide statistics for the admin dashboard."""
    stats = await get_platform_stats(session)
    return AdminStatsResponse(**stats)


# --- Users ---


@router.get("/users", response_model=PaginatedResponse)
async def admin_list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    org_id: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> PaginatedResponse:
    """List all users across all orgs (platform admin only)."""
    stmt = (
        select(User)
        .options(selectinload(User.role))
        .offset(skip)
        .limit(limit)
        .order_by(User.created_at.desc())
    )
    count_stmt = select(func.count(User.id))

    if org_id:
        stmt = stmt.where(User.org_id == org_id)
        count_stmt = count_stmt.where(User.org_id == org_id)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
        count_stmt = count_stmt.where(User.is_active.is_(is_active))
    if search:
        pattern = f"%{search}%"
        search_filter = or_(User.email.ilike(pattern), User.full_name.ilike(pattern))
        stmt = stmt.where(search_filter)
        count_stmt = count_stmt.where(search_filter)

    result = await session.execute(stmt)
    users = list(result.scalars().all())
    total = (await session.execute(count_stmt)).scalar_one()

    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def admin_get_user(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> UserResponse:
    """Get a single user by ID."""
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def admin_update_user_route(
    user_id: str,
    data: AdminUserUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> UserResponse:
    """Update a user (role, org, team, status)."""
    user = await admin_update_user(session, user_id, data)

    # Write audit log
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_update_user",
        resource_type="user",
        resource_id=user_id,
        details=data.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return UserResponse.model_validate(user)


@router.put("/users/{user_id}/reset-password", status_code=204)
async def admin_reset_password_route(
    user_id: str,
    data: AdminResetPassword,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> None:
    """Reset a user's password (platform admin only).

    Sets a new password for a local auth user. The user will need to
    use this new password on their next login.
    """
    await admin_reset_password(session, user_id, data.new_password)

    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_reset_password",
        resource_type="user",
        resource_id=user_id,
        details={"target_user_id": user_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/users", response_model=UserResponse, status_code=201)
async def admin_create_user(
    data: AdminUserCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_admin_user),
) -> User:
    """Create a new local user account.

    Requires ``platform_admin`` or ``org_admin`` role.
    ``org_admin`` callers are scoped to their own organization — the
    user is created in the caller's org and the ``org_id`` field in
    the payload is ignored.
    """
    scope = current_user.role or ""

    if scope == "org_admin":
        data.org_id = current_user.org_id or data.org_id

    from core.exceptions import AlreadyExistsError

    existing = await get_user_by_email(session, data.email)
    if existing is not None:
        raise AlreadyExistsError("User", data.email)

    user = await create_user(session, data)

    await write_audit_log(
        session,
        user_id=current_user.sub,
        action="admin_create_user",
        resource_type="user",
        resource_id=user.id,
        details={"email": data.email, "full_name": data.full_name, "org_id": data.org_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await session.commit()
    return user


@router.delete("/users/by-email/{email}", status_code=200)
async def admin_delete_user_by_email(
    email: str,
    request: Request,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(get_async_session),
    current_user: TokenPayload = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Delete a local user and all associated data.

    Only **local** users (auth_method = ``"local"``) can be removed.
    Users holding ``platform_admin`` or ``org_admin`` roles are
    protected from deletion.

    ``platform_admin`` callers may delete any local user across all orgs.
    ``org_admin`` callers are scoped to their own organization.
    """
    result = await session.execute(
        select(User).where(User.email == email).options(selectinload(User.role))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User", email)

    summary = await admin_delete_user(
        session,
        str(user.id),
        dry_run=dry_run,
        caller_role=current_user.role or "",
        caller_org_id=current_user.org_id,
    )

    if not dry_run:
        await write_audit_log(
            session,
            user_id=current_user.sub,
            action="admin_delete_user",
            resource_type="user",
            resource_id=str(user.id),
            details={"target_email": email, "target_org_id": str(user.org_id)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

    if not dry_run:
        await session.commit()

    return summary


# --- Orgs ---


@router.get("/orgs", response_model=PaginatedResponse)
async def admin_list_orgs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> PaginatedResponse:
    """List all organizations."""
    stmt = select(Org).offset(skip).limit(limit).order_by(Org.created_at.desc())
    result = await session.execute(stmt)
    orgs = list(result.scalars().all())
    total = (await session.execute(select(func.count(Org.id)))).scalar_one()

    return PaginatedResponse(
        items=[OrgResponse.model_validate(o) for o in orgs],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/teams", response_model=PaginatedResponse)
async def admin_list_teams(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> PaginatedResponse:
    """List all teams across organizations."""
    teams = await list_all_teams(session, skip=skip, limit=limit)
    total = await count_all_teams(session)
    return PaginatedResponse(
        items=[TeamResponse.model_validate(t) for t in teams],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/orgs", response_model=OrgResponse, status_code=201)
async def admin_create_org(
    data: OrgCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> OrgResponse:
    """Create a new organization."""
    org = await create_org(
        session,
        name=data.name,
        slug=data.slug,
        description=data.description,
        settings=data.settings,
    )
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_create_org",
        resource_type="org",
        resource_id=org.id,
        details={"name": data.name, "slug": data.slug},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return OrgResponse.model_validate(org)


@router.put("/orgs/{org_id}", response_model=OrgResponse)
async def admin_update_org(
    org_id: str,
    data: OrgUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> OrgResponse:
    """Update an organization."""
    org = await update_org(session, org_id, data)
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_update_org",
        resource_type="org",
        resource_id=org_id,
        details=data.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return OrgResponse.model_validate(org)


# --- Roles ---


@router.get("/roles", response_model=list[RoleResponse])
async def admin_list_roles(
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> list[RoleResponse]:
    """List all available roles."""
    roles = await list_roles(session)
    return [RoleResponse.model_validate(r) for r in roles]


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def admin_create_role(
    data: RoleCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> RoleResponse:
    """Create a new RBAC role."""
    role = await create_role(
        session,
        name=data.name,
        description=data.description,
        permissions=data.permissions,
    )
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_create_role",
        resource_type="role",
        resource_id=role.id,
        details={"name": data.name, "permissions": data.permissions},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return RoleResponse.model_validate(role)


@router.put("/roles/{role_id}", response_model=RoleResponse)
async def admin_update_role(
    role_id: str,
    data: RoleUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> RoleResponse:
    """Update an RBAC role."""
    role = await update_role(session, role_id, data)
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_update_role",
        resource_type="role",
        resource_id=role_id,
        details=data.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return RoleResponse.model_validate(role)


# --- LLM Providers ---


def _llm_response(p: Any) -> LLMProviderResponse:
    """Build an LLMProviderResponse from an ORM model, including org_name."""
    data = LLMProviderResponse.model_validate(p)
    org = getattr(p, "org", None)
    if org is not None:
        data.org_name = getattr(org, "name", None)
    data.has_api_key = getattr(p, "encrypted_api_key", None) is not None
    return data


@router.get("/llm-providers", response_model=PaginatedResponse)
async def admin_list_llm_providers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> PaginatedResponse:
    """List all LLM providers (platform-wide)."""
    items, total = await list_llm_providers(session, skip=skip, limit=limit)
    return PaginatedResponse(
        items=[_llm_response(p) for p in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/llm-providers", response_model=LLMProviderResponse, status_code=201)
async def admin_create_llm_provider(
    data: LLMProviderCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> LLMProviderResponse:
    """Create a new LLM provider."""
    org_id = data.org_id
    if not org_id:
        raise HTTPException(status_code=422, detail="org_id is required")

    p = await create_llm_provider(
        session,
        name=data.name,
        slug=data.slug,
        description=data.description,
        provider_type=data.provider_type,
        base_url=data.base_url,
        api_key=data.api_key,
        default_model=data.default_model,
        supported_models=data.supported_models,
        max_tokens=data.max_tokens,
        is_default=data.is_default,
        org_id=org_id,
        created_by=admin.sub,
    )
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_create_llm_provider",
        resource_type="llm_provider",
        resource_id=p.id,
        details={"name": data.name, "slug": data.slug, "org_id": org_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return _llm_response(p)


@router.put("/llm-providers/{provider_id}", response_model=LLMProviderResponse)
async def admin_update_llm_provider(
    provider_id: str,
    data: LLMProviderUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> LLMProviderResponse:
    """Update an LLM provider."""
    update_data = data.model_dump(exclude_unset=True)
    p = await update_llm_provider(session, provider_id, update_data)
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_update_llm_provider",
        resource_type="llm_provider",
        resource_id=provider_id,
        details=update_data,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return _llm_response(p)


@router.delete("/llm-providers/{provider_id}", status_code=204)
async def admin_delete_llm_provider(
    provider_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> None:
    """Delete an LLM provider."""
    await delete_llm_provider(session, provider_id)
    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_delete_llm_provider",
        resource_type="llm_provider",
        resource_id=provider_id,
        details={},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# --- Object Store Buckets ---


def _bucket_response(b: ObjectStoreBucket) -> BucketResponse:
    """Build a BucketResponse with org_name from eagerly-loaded relationship."""
    data = BucketResponse.model_validate(b)
    org = getattr(b, "org", None)
    if org is not None:
        data.org_name = getattr(org, "name", None)
    data.has_access_key = getattr(b, "encrypted_access_key", None) is not None
    data.has_secret_key = getattr(b, "encrypted_secret_key", None) is not None
    return data


@router.get("/buckets", response_model=PaginatedResponse)
async def admin_list_buckets(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> PaginatedResponse:
    """List all object store buckets (platform-wide)."""
    items, total = await list_buckets(session, skip=skip, limit=limit)
    return PaginatedResponse(
        items=[_bucket_response(b) for b in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/buckets", response_model=BucketResponse, status_code=201)
async def admin_create_bucket(
    data: BucketCreate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: TokenPayload = Depends(get_current_superuser),
) -> BucketResponse:
    """Register a new object store bucket (platform admin)."""
    from core.security.fernet import encrypt_value

    encrypted_access_key = encrypt_value(data.access_key) if data.access_key else None
    encrypted_secret_key = encrypt_value(data.secret_key) if data.secret_key else None

    b = await create_bucket(
        session=session,
        data=data,
        org_id=cast(str, data.org_id or admin.org_id),
        user_id=admin.sub,
        encrypted_access_key=encrypted_access_key,
        encrypted_secret_key=encrypted_secret_key,
    )

    await write_audit_log(
        session,
        user_id=admin.sub,
        action="admin_create_bucket",
        resource_type="object_store_bucket",
        resource_id=b.id,
        details={
            "name": data.name,
            "slug": data.slug,
            "bucket_name": data.bucket_name,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return _bucket_response(b)


# --- Audit logs ---


@router.get("/audit-logs", response_model=PaginatedResponse)
async def admin_list_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    action: str | None = None,
    user_id: str | None = None,
    resource_type: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> PaginatedResponse:
    """List audit log entries with optional filters."""
    logs = await list_audit_logs(
        session,
        skip=skip,
        limit=limit,
        action=action,
        user_id=user_id,
        resource_type=resource_type,
    )
    total = await count_audit_logs(
        session,
        action=action,
        user_id=user_id,
        resource_type=resource_type,
    )
    return PaginatedResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        skip=skip,
        limit=limit,
    )


# --- Service health ---


@router.get("/services/health", response_model=list[ServiceHealthResponse])
async def admin_services_health(
    _admin: TokenPayload = Depends(get_current_superuser),
) -> list[ServiceHealthResponse]:
    """Check health of all backend microservices."""
    results = await check_services_health()
    return [ServiceHealthResponse(**r) for r in results]


@router.get("/services/{service_name}/logs", response_model=ServiceLogsResponse)
async def admin_service_logs(
    service_name: str,
    tail: int = Query(200, ge=1, le=5000),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> ServiceLogsResponse:
    """Fetch recent application logs for a service (reads .dev-logs files)."""
    logs = read_service_logs(service_name, tail=tail)
    return ServiceLogsResponse(service_name=service_name, logs=logs)


# --- Docker containers ---


@router.get("/docker/containers", response_model=list[DockerContainerResponse])
async def admin_docker_containers(
    all: bool = Query(True, description="Include stopped containers"),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> list[DockerContainerResponse]:
    """List all Docker containers with status."""
    containers = list_docker_containers(all_containers=all)
    # If there's an error dict, return it as a single errored entry
    if containers and "error" in containers[0]:
        return []
    return [DockerContainerResponse(**c) for c in containers]


@router.get("/docker/containers/{container_id}/logs", response_model=DockerContainerLogsResponse)
async def admin_docker_container_logs(
    container_id: str,
    tail: int = Query(200, ge=1, le=5000),
    _admin: TokenPayload = Depends(get_current_superuser),
) -> DockerContainerLogsResponse:
    """Fetch recent logs from a Docker container."""
    # Resolve container name for display
    containers = list_docker_containers()
    name = container_id
    for c in containers:
        if c.get("id") == container_id or c.get("name") == container_id:
            name = c.get("name", container_id)
            break

    logs = get_docker_container_logs(container_id, tail=tail)
    return DockerContainerLogsResponse(
        container_id=container_id,
        container_name=name,
        logs=logs,
    )
