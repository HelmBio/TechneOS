"""Admin CRUD operations — platform-wide stats, user management, audit logs, docker."""

import logging
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, cast

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.audit import write_audit_log as write_audit_log
from core.auth.providers import hash_password
from core.config import get_settings
from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.agent import AgentDefinition, AgenticRun, AgenticTask
from core.models.artifact import ComputeArtifact
from core.models.bucket import ObjectStoreBucket
from core.models.common import AdminUserUpdate, OrgUpdate, RoleUpdate
from core.models.compute_backend import ComputeBackend
from core.models.dataset import Dataset, DatasetVersion
from core.models.llm_provider import LLMProvider
from core.models.notification import Notification, Subscription
from core.models.pipeline import (
    Pipeline,
    PipelineRun,
    PipelineRunArtifact,
    PipelineStepRun,
    PipelineVersion,
)
from core.models.tool import Tool, ToolVersion
from core.models.user import ApiKey, AuditLog, Org, Role, Team, User

logger = logging.getLogger(__name__)

# Role names that are protected from deletion.
_PROTECTED_ROLES = frozenset({"platform_admin", "org_admin"})

# Ordered list of (key, model, column) for dependent tables.
# Deletion order matters: children before parents, junction before main.
_USER_DEPENDENTS: list[tuple[str, type, str]] = [
    ("pipeline_run_artifacts", PipelineRunArtifact, "run_id"),
    ("pipeline_step_runs", PipelineStepRun, "run_id"),
    ("pipeline_runs", PipelineRun, "submitted_by"),
    ("pipeline_versions", PipelineVersion, "created_by"),
    ("pipelines", Pipeline, "created_by"),
    ("agent_tasks", AgenticTask, "submitted_by"),
    ("agents", AgentDefinition, "created_by"),
    ("agent_runs", AgenticRun, "created_by"),
    ("tool_versions", ToolVersion, "created_by"),
    ("tools", Tool, "created_by"),
    ("dataset_versions", DatasetVersion, "created_by"),
    ("datasets", Dataset, "created_by"),
    ("llm_providers", LLMProvider, "created_by"),
    ("subscriptions", Subscription, "user_id"),
    ("notifications", Notification, "user_id"),
    ("api_keys", ApiKey, "user_id"),
    ("audit_logs", AuditLog, "user_id"),
]


async def _resolve_pipeline_run_ids(session: AsyncSession, user_id: str) -> list[str]:
    result = await session.execute(
        select(PipelineRun.id).where(PipelineRun.submitted_by == user_id)
    )
    return [str(r) for r in result.scalars().all()]


async def admin_delete_user(
    session: AsyncSession,
    user_id: str,
    *,
    dry_run: bool = False,
    caller_role: str = "",
    caller_org_id: str | None = None,
) -> dict[str, Any]:
    """Delete a user (local or SSO) and all associated data.

    Validates that the user does not hold a protected role.  When
    *caller_role* is ``org_admin`` the target user must belong to the
    caller's org.  The matching Keycloak account is removed separately,
    after the commit, by :func:`delete_keycloak_user`.

    Returns a summary dict with dependent counts (and ``"deleted": True``
    when *dry_run* is ``False``).
    """
    result = await session.execute(
        select(User).where(User.id == user_id).options(selectinload(User.role))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User", user_id)

    user_email = user.email
    user_org_id = str(user.org_id)
    auth_method = user.auth_method

    # --- Validation ---

    # Block removal of users with protected roles
    if user.role_id:
        role_result = await session.execute(select(Role.name).where(Role.id == user.role_id))
        role_name = role_result.scalar_one_or_none()
        if role_name and role_name in _PROTECTED_ROLES:
            if role_name == "platform_admin":
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot remove platform_admin '{user_email}'",
                )
            if caller_role == "org_admin":
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot remove user '{user_email}' with role '{role_name}'",
                )

    # Org_admin can only delete users in their own org
    if caller_role == "org_admin" and caller_org_id != user_org_id:
        raise HTTPException(
            status_code=403,
            detail="Org admins can only remove users within their own organization",
        )

    # --- Count / delete dependents ---

    run_ids = await _resolve_pipeline_run_ids(session, user_id)

    dependent_counts: dict[str, int] = {}
    total = 0

    for label, model, column in _USER_DEPENDENTS:
        ids = run_ids if label in ("pipeline_run_artifacts", "pipeline_step_runs") else [user_id]

        if not ids:
            count = 0
        else:
            col = getattr(model, column)
            count_result = await session.execute(select(func.count()).where(col.in_(ids)))
            count = int(count_result.scalar() or 0)

        dependent_counts[label] = count
        total += count

        if count and not dry_run and ids:
            col = getattr(model, column)
            await session.execute(delete(model).where(col.in_(ids)))

    if not dry_run:
        await session.execute(delete(User).where(User.id == user_id))

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "user": {
            "id": user_id,
            "email": user_email,
            "auth_method": auth_method,
            "org_id": user_org_id,
        },
        "dependents": dependent_counts,
        "total_dependents": total,
    }

    if not dry_run:
        summary["deleted"] = True

    return summary


async def delete_keycloak_user(external_id: str | None, email: str) -> str:
    """Remove a deleted user's Keycloak account so they can't sign in again.

    Without this, a deleted SSO user would simply be re-provisioned on their
    next Google/GitHub sign-in.  Looks the account up by ``external_id``
    (the Keycloak ``sub``) and falls back to email; the email must match,
    so an enterprise OAuth2 subject never deletes an unrelated account.

    Returns ``"deleted"``, ``"not_found"``, ``"skipped"`` (Keycloak not
    configured) or ``"failed"``.  Never raises: the platform user is
    already gone by the time this runs.
    """
    if not get_settings().keycloak_configured:
        return "skipped"

    from core.auth.keycloak_admin import get_keycloak_admin

    kc = get_keycloak_admin()
    try:
        kc_user = await kc.get_user_by_id(external_id) if external_id else None
        if kc_user is None or (kc_user.get("email") or "").lower() != email.lower():
            kc_user = await kc.get_user_by_email(email)
        if kc_user is None:
            return "not_found"
        return "deleted" if await kc.delete_user(kc_user["id"]) else "not_found"
    except Exception:
        logger.warning("Failed to delete Keycloak user for %s", email, exc_info=True)
        return "failed"


# --- Stats ---


async def get_platform_stats(session: AsyncSession) -> dict[str, Any]:
    """Aggregate platform-wide statistics."""
    total_users = (await session.execute(select(func.count(User.id)))).scalar_one()
    active_users = (
        await session.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    ).scalar_one()
    total_orgs = (await session.execute(select(func.count(Org.id)))).scalar_one()
    active_orgs = (
        await session.execute(select(func.count(Org.id)).where(Org.is_active.is_(True)))
    ).scalar_one()
    total_teams = (await session.execute(select(func.count(Team.id)))).scalar_one()
    total_roles = (await session.execute(select(func.count(Role.id)))).scalar_one()
    total_llm_providers = (await session.execute(select(func.count(LLMProvider.id)))).scalar_one()
    default_llm_providers = (
        await session.execute(
            select(func.count(LLMProvider.id)).where(LLMProvider.is_default.is_(True))
        )
    ).scalar_one()
    total_buckets = (await session.execute(select(func.count(ObjectStoreBucket.id)))).scalar_one()
    default_buckets = (
        await session.execute(
            select(func.count(ObjectStoreBucket.id)).where(ObjectStoreBucket.is_default.is_(True))
        )
    ).scalar_one()
    total_compute_backends = (
        await session.execute(select(func.count(ComputeBackend.id)))
    ).scalar_one()
    enabled_compute_backends = (
        await session.execute(
            select(func.count(ComputeBackend.id)).where(ComputeBackend.status == "enabled")
        )
    ).scalar_one()
    total_artifacts = (
        await session.execute(
            select(func.count(ComputeArtifact.id)).where(
                ComputeArtifact.status == "available"
            )
        )
    ).scalar_one()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_orgs": total_orgs,
        "active_orgs": active_orgs,
        "total_teams": total_teams,
        "total_roles": total_roles,
        "total_llm_providers": total_llm_providers,
        "default_llm_providers": default_llm_providers,
        "total_buckets": total_buckets,
        "default_buckets": default_buckets,
        "total_compute_backends": total_compute_backends,
        "enabled_compute_backends": enabled_compute_backends,
        "total_artifacts": total_artifacts,
    }


# --- Admin user update (extended) ---


async def admin_update_user(session: AsyncSession, user_id: str, data: AdminUserUpdate) -> User:
    """Update a user with admin-level fields (org_id, role, etc.)."""
    result = await session.execute(
        select(User).where(User.id == user_id).options(selectinload(User.role))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User", user_id)

    update_data = data.model_dump(exclude_unset=True)

    # Handle role_name -> role_id resolution
    if "role_name" in update_data:
        role_name = update_data.pop("role_name")
        if role_name:
            role_result = await session.execute(select(Role).where(Role.name == role_name))
            role = role_result.scalar_one_or_none()
            if role:
                user.role_id = role.id

    for field, value in update_data.items():
        setattr(user, field, value)

    await session.flush()
    return user


async def admin_reset_password(session: AsyncSession, user_id: str, new_password: str) -> User:
    """Admin-initiated password reset for a local auth user.

    Sets a new hashed password. SSO-only users (no existing password) will
    gain local auth capability after this operation.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User", user_id)

    user.hashed_password = hash_password(new_password)
    await session.flush()
    return user


# --- Roles ---


async def list_roles(session: AsyncSession) -> list[Role]:
    """List all roles."""
    result = await session.execute(select(Role).order_by(Role.name))
    return list(result.scalars().all())


async def create_role(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    permissions: list[str] | None = None,
) -> Role:
    """Create a new RBAC role."""
    role = Role(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        permissions=permissions or [],
    )
    session.add(role)
    await session.flush()
    return role


async def create_org(
    session: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None = None,
    settings: dict[str, Any] | None = None,
) -> Org:
    """Create a new organization."""
    org = Org(
        id=str(uuid.uuid4()),
        name=name,
        slug=slug,
        description=description,
        settings=settings or {},
        is_active=True,
    )
    session.add(org)
    await session.flush()
    return org


async def update_role(session: AsyncSession, role_id: str, data: RoleUpdate) -> Role:
    """Update an existing role's description and/or permissions."""
    result = await session.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role", role_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(role, field, value)

    await session.flush()
    return role


async def update_org(session: AsyncSession, org_id: str, data: OrgUpdate) -> Org:
    """Update an existing organization."""
    result = await session.execute(select(Org).where(Org.id == org_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise NotFoundError("Org", org_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(org, field, value)

    await session.flush()
    return org


# --- LLM Providers ---


async def list_llm_providers(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[LLMProvider], int]:
    """List all LLM providers (platform-wide)."""
    total = (await session.execute(select(func.count(LLMProvider.id)))).scalar_one()
    stmt = select(LLMProvider).order_by(LLMProvider.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def create_llm_provider(
    session: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None = None,
    provider_type: str = "openai_compatible",
    base_url: str | None = None,
    api_key: str | None = None,
    default_model: str,
    supported_models: list[str] | None = None,
    max_tokens: int | None = None,
    is_default: bool = False,
    org_id: str,
    created_by: str,
) -> LLMProvider:
    """Create a new LLM provider."""
    from core.security.fernet import encrypt_value

    existing = await session.execute(select(LLMProvider).where(LLMProvider.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise AlreadyExistsError("LLMProvider", slug)

    if is_default:
        await _clear_llm_defaults(session, org_id)

    encrypted_api_key = encrypt_value(api_key) if api_key else None

    p = LLMProvider(
        id=str(uuid.uuid4()),
        name=name,
        slug=slug,
        description=description,
        provider_type=provider_type,
        base_url=base_url.strip() if base_url else None,
        encrypted_api_key=encrypted_api_key,
        default_model=default_model,
        supported_models=supported_models or [],
        max_tokens=max_tokens,
        is_default=is_default,
        org_id=org_id,
        created_by=created_by,
    )
    session.add(p)
    await session.flush()
    await session.refresh(p, ["org", "creator"])
    return p


async def update_llm_provider(
    session: AsyncSession,
    provider_id: str,
    data: dict[str, Any],
) -> LLMProvider:
    """Update an existing LLM provider."""
    from core.security.fernet import encrypt_value

    result = await session.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if p is None:
        raise NotFoundError("LLMProvider", provider_id)

    if data.get("is_default"):
        await _clear_llm_defaults(session, p.org_id)

    # Strip whitespace from base_url
    if "base_url" in data and data["base_url"] is not None:
        data["base_url"] = data["base_url"].strip()

    # Encrypt api_key if provided, then store in encrypted_api_key
    api_key = data.pop("api_key", None)
    if api_key is not None:
        data["encrypted_api_key"] = encrypt_value(api_key)

    for field, value in data.items():
        setattr(p, field, value)

    await session.flush()
    await session.refresh(p, ["org", "creator"])
    return p


# --- Object Store Buckets ---


async def list_buckets(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[ObjectStoreBucket], int]:
    """List all buckets (platform-wide)."""
    total = (await session.execute(select(func.count(ObjectStoreBucket.id)))).scalar_one()
    stmt = (
        select(ObjectStoreBucket)
        .order_by(ObjectStoreBucket.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def delete_llm_provider(session: AsyncSession, provider_id: str) -> None:
    """Delete an LLM provider."""
    result = await session.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if p is None:
        raise NotFoundError("LLMProvider", provider_id)
    await session.delete(p)
    await session.flush()


async def _clear_llm_defaults(session: AsyncSession, org_id: str) -> None:
    """Clear the is_default flag for all providers in an org."""
    await session.execute(
        update(LLMProvider)
        .where(LLMProvider.org_id == org_id, LLMProvider.is_default.is_(True))
        .values(is_default=False)
    )


# --- Audit logs ---


async def list_audit_logs(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    action: str | None = None,
    user_id: str | None = None,
    resource_type: str | None = None,
) -> list[AuditLog]:
    """List audit logs with optional filters."""
    stmt = select(AuditLog).offset(skip).limit(limit).order_by(AuditLog.timestamp.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_audit_logs(
    session: AsyncSession,
    action: str | None = None,
    user_id: str | None = None,
    resource_type: str | None = None,
) -> int:
    """Count audit logs with optional filters."""
    stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    result = await session.execute(stmt)
    return result.scalar_one()


# --- Service health ---


async def check_services_health() -> list[dict[str, Any]]:
    """Ping all microservice /health endpoints and return status."""
    settings = get_settings()
    services = [
        ("auth", settings.auth_service_url),
        ("dataset", settings.dataset_service_url),
        ("tool", settings.tool_service_url),
        ("pipeline", settings.pipeline_service_url),
        ("agent", settings.agent_service_url),
        ("app", settings.app_service_url),
        ("task", settings.task_service_url),
        ("notification", settings.notification_service_url),
    ]

    results = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services:
            health_url = f"{url}/health"
            start = time.monotonic()
            try:
                resp = await client.get(health_url)
                latency = (time.monotonic() - start) * 1000
                status = "healthy" if resp.status_code == 200 else "unhealthy"
            except (httpx.ConnectError, httpx.TimeoutException):
                latency = None
                status = "unreachable"
            results.append(
                {
                    "name": name,
                    "url": url,
                    "status": status,
                    "latency_ms": round(latency, 1) if latency is not None else None,
                }
            )
    return results


# --- Service logs ---

VALID_SERVICE_NAMES = frozenset(
    [
        "auth",
        "dataset",
        "tool",
        "pipeline",
        "agent",
        "app",
        "task",
        "notification",
        "gateway",
    ]
)


def _find_dev_logs_dir() -> Path | None:
    """Locate the .dev-logs directory by walking up from the project root."""
    # Try common locations relative to the running process
    candidates = [
        Path(os.environ.get("TECHNEOS_LOG_DIR", "")) if os.environ.get("TECHNEOS_LOG_DIR") else None,
        Path(__file__).resolve().parents[6]
        / ".dev-logs",  # packages/services/auth/src/auth_service/crud -> root
        Path.cwd() / ".dev-logs",
    ]
    for p in candidates:
        if p is not None and p.is_dir():
            return p
    return None


def read_service_logs(service_name: str, tail: int = 200) -> str:
    """Read the last *tail* lines from a service's dev log file.

    Falls back to Docker container logs when running in production where
    .dev-logs/ does not exist.
    """
    if service_name not in VALID_SERVICE_NAMES:
        return f"Unknown service: {service_name}. Valid services: {', '.join(sorted(VALID_SERVICE_NAMES))}"

    # Try filesystem logs (local dev)
    log_dir = _find_dev_logs_dir()
    if log_dir is not None:
        log_file = log_dir / f"{service_name}.log"
        if log_file.exists():
            try:
                with open(log_file, "rb") as f:
                    lines: deque[str] = deque(maxlen=tail)
                    for raw_line in f:
                        lines.append(raw_line.decode("utf-8", errors="replace"))
                    return "".join(lines)
            except Exception as e:
                return f"Error reading logs: {e}"

    # Fall back to Docker container logs (production)
    try:
        import docker

        client = docker.from_env()
        # Match any container whose name contains the service name
        # e.g. "techneos-auth-service-1" for "auth"
        candidates = [c for c in client.containers.list(all=False) if service_name in c.name]
        if not candidates:
            return f"No running container found for '{service_name}'"
        container = candidates[0]
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        client.close()
        return cast(str, logs)
    except Exception as e:
        return f"Error fetching Docker logs: {e}"


# --- Docker containers ---


def _get_docker_client() -> Any:
    """Get a Docker client connected to the local daemon."""
    import docker

    return docker.from_env()


def list_docker_containers(all_containers: bool = True) -> list[dict[str, Any]]:
    """List Docker containers with status info."""
    # Compose names containers "<project>-<service>-<n>"; read the project
    # name from the standard Compose env var instead of hardcoding it, so
    # this doesn't drift if docker-compose.yml's `name:` is ever repointed.
    project_prefix = os.environ.get("COMPOSE_PROJECT_NAME", "techneos") + "-"
    try:
        client = _get_docker_client()
        containers = client.containers.list(all=all_containers)
        results = []
        for c in containers:
            # Only include project infrastructure containers
            if not c.name.startswith(project_prefix):
                continue

            # Parse health from status string
            health = None
            if c.attrs.get("State", {}).get("Health"):
                health = c.attrs["State"]["Health"].get("Status")

            # Resolve image tag — the image may have been removed
            try:
                image = str(c.image.tags[0]) if c.image.tags else str(c.image.short_id)
            except Exception:
                image = c.attrs.get("Config", {}).get("Image", "unknown")

            results.append(
                {
                    "id": c.short_id,
                    "name": c.name,
                    "image": image,
                    "status": c.status,
                    "health": health,
                    "state": c.attrs.get("State", {}).get("Status", "unknown"),
                    "created": c.attrs.get("Created", ""),
                    "ports": _format_ports(c.attrs.get("NetworkSettings", {}).get("Ports", {})),
                }
            )
        client.close()
        return results
    except Exception as e:
        return [{"error": str(e)}]


def get_docker_container_logs(container_id: str, tail: int = 200) -> str:
    """Fetch recent logs from a Docker container."""
    try:
        client = _get_docker_client()
        container = client.containers.get(container_id)
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        client.close()
        return cast(str, logs)
    except Exception as e:
        return f"Error fetching logs: {e}"


def _format_ports(ports_dict: dict[str, Any]) -> list[str]:
    """Format Docker port bindings into readable strings."""
    result = []
    for container_port, bindings in ports_dict.items():
        if bindings:
            for b in bindings:
                host = b.get("HostIp", "0.0.0.0")
                host_port = b.get("HostPort", "?")
                result.append(f"{host}:{host_port}->{container_port}")
        else:
            result.append(container_port)
    return result
