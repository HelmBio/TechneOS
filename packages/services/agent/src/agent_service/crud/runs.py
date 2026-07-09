"""CRUD operations for agentic tasks."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.models.agent import AgenticTask
from core.schemas.agent import AgenticTaskUpdate


async def get_agentic_task(session: AsyncSession, task_id: str) -> AgenticTask:
    """Get an agentic task by ID."""
    result = await session.execute(select(AgenticTask).where(AgenticTask.id == task_id))
    r = result.scalar_one_or_none()
    if r is None:
        raise NotFoundError("AgenticTask", task_id)
    return r


async def create_agentic_task(
    session: AsyncSession,
    agent_id: str | None,
    task: str,
    context: dict[str, Any],
    org_id: str,
    user_id: str,
    agentic_run_id: str | None = None,
) -> AgenticTask:
    """Create a new agentic task."""
    r = AgenticTask(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        agentic_run_id=agentic_run_id,
        status="pending",
        task=task,
        context=context,
        org_id=org_id,
        submitted_by=user_id,
    )
    session.add(r)
    await session.flush()
    return r


async def update_agentic_task(
    session: AsyncSession, task_id: str, data: AgenticTaskUpdate
) -> AgenticTask:
    """Update an agentic task (status, result, messages, tool_calls, etc.)."""
    r = await get_agentic_task(session, task_id)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(r, field, value)
    await session.flush()
    return r


async def cancel_agentic_task(session: AsyncSession, task_id: str) -> AgenticTask:
    """Cancel a pending or running agentic task."""
    r = await get_agentic_task(session, task_id)
    if r.status in ("completed", "failed", "cancelled"):
        from core.exceptions import ValidationError

        raise ValidationError(f"Cannot cancel task in '{r.status}' state")
    r.status = "cancelled"
    r.finished_at = datetime.now(UTC)
    await session.flush()
    return r


async def list_agentic_tasks(
    session: AsyncSession,
    agent_id: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
) -> tuple[list[AgenticTask], int]:
    """List agentic tasks with filters."""
    stmt = select(AgenticTask)
    count_stmt = select(func.count(AgenticTask.id))

    # Apply scope filters from the route layer
    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if agent_id:
        stmt = stmt.where(AgenticTask.agent_id == agent_id)
        count_stmt = count_stmt.where(AgenticTask.agent_id == agent_id)

    if status:
        stmt = stmt.where(AgenticTask.status == status)
        count_stmt = count_stmt.where(AgenticTask.status == status)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(AgenticTask.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
