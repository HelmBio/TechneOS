"""Shared audit-log helper — usable from any service."""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.models.user import AuditLog


async def write_audit_log(
    session: AsyncSession,
    *,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Write an audit log entry."""
    log = AuditLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(log)
    await session.flush()
    return log
