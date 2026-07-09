"""CRUD operations for agentic runs."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions import NotFoundError
from core.models.agent import AgenticRun, AgenticTask


async def get_agentic_run(session: AsyncSession, agentic_run_id: str) -> AgenticRun:
    """Get an agentic run by ID."""
    result = await session.execute(select(AgenticRun).where(AgenticRun.id == agentic_run_id))
    c = result.scalar_one_or_none()
    if c is None:
        raise NotFoundError("AgenticRun", agentic_run_id)
    return c


async def get_agentic_run_with_tasks(session: AsyncSession, agentic_run_id: str) -> AgenticRun:
    """Get an agentic run with its tasks eagerly loaded."""
    result = await session.execute(
        select(AgenticRun)
        .where(AgenticRun.id == agentic_run_id)
        .options(selectinload(AgenticRun.tasks))
    )
    c = result.scalar_one_or_none()
    if c is None:
        raise NotFoundError("AgenticRun", agentic_run_id)
    return c


async def create_agentic_run(
    session: AsyncSession,
    agent_id: str | None,
    org_id: str,
    user_id: str,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgenticRun:
    """Create a new agentic run."""
    c = AgenticRun(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        title=title,
        metadata_=metadata or {},
        org_id=org_id,
        created_by=user_id,
    )
    session.add(c)
    await session.flush()
    return c


async def list_agentic_runs(
    session: AsyncSession,
    agent_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List agentic runs with task counts and latest task status."""
    # Subquery for task count
    task_count_sq = (
        select(func.count(AgenticTask.id))
        .where(AgenticTask.agentic_run_id == AgenticRun.id)
        .correlate(AgenticRun)
        .scalar_subquery()
        .label("task_count")
    )

    # Subquery for latest task status (by created_at desc)
    latest_status_sq = (
        select(AgenticTask.status)
        .where(AgenticTask.agentic_run_id == AgenticRun.id)
        .correlate(AgenticRun)
        .order_by(AgenticTask.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("latest_task_status")
    )

    stmt = select(AgenticRun, task_count_sq, latest_status_sq)
    count_stmt = select(func.count(AgenticRun.id))

    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if agent_id:
        stmt = stmt.where(AgenticRun.agent_id == agent_id)
        count_stmt = count_stmt.where(AgenticRun.agent_id == agent_id)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(AgenticRun.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    # Attach computed fields as attributes on each run object
    items = []
    for run, task_count, latest_task_status in rows:
        run.task_count = task_count or 0
        run.latest_task_status = latest_task_status
        items.append(run)

    return items, total


async def delete_agentic_run(session: AsyncSession, agentic_run_id: str) -> None:
    """Delete an agentic run and its associated tasks (via CASCADE)."""
    run = await get_agentic_run(session, agentic_run_id)
    await session.delete(run)
    await session.flush()


async def update_agentic_run_title(
    session: AsyncSession, agentic_run_id: str, title: str
) -> AgenticRun:
    """Update an agentic run's title."""
    run = await get_agentic_run(session, agentic_run_id)
    run.title = title
    await session.flush()
    return run


async def get_agentic_run_messages(session: AsyncSession, agentic_run_id: str) -> list[dict[str, Any]]:
    """Collect all messages from tasks in an agentic run, ordered chronologically.

    Returns a flat list of message dicts suitable for passing as
    ``message_history`` to PydanticAI's ``agent.run_stream()``.
    """
    result = await session.execute(
        select(AgenticTask)
        .where(
            AgenticTask.agentic_run_id == agentic_run_id,
            AgenticTask.status == "completed",
        )
        .order_by(AgenticTask.created_at.asc())
    )
    tasks = result.scalars().all()

    all_messages: list[dict[str, Any]] = []
    for task in tasks:
        if task.messages:
            all_messages.extend(task.messages)
    return all_messages
