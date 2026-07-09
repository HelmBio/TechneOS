"""Agentic run routes — create, list, get, and get with tasks."""
from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.crud.agents import get_agent_by_id_or_slug, resolve_agent_id_filter
from agent_service.crud.conversations import (
    create_agentic_run,
    delete_agentic_run,
    get_agentic_run,
    get_agentic_run_with_tasks,
    list_agentic_runs,
    update_agentic_run_title,
)
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.database.postgres import get_async_session
from core.models.agent import AgenticRun
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.agent import (
    AgenticRunCreate,
    AgenticRunDetail,
    AgenticRunResponse,
    AgenticRunUpdate,
    AgenticTaskResponse,
)

router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


@router.post("", response_model=AgenticRunResponse, status_code=201)
async def create_agentic_run_endpoint(
    data: AgenticRunCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-run", "execute", "own")),
) -> AgenticRunResponse:
    """Create a new agentic run session with an agent."""
    org_id = _require_org(current_user)

    # Validate agent exists and check access
    agent = await get_agent_by_id_or_slug(session, cast(str, data.agent_id))
    check_resource_access(current_user, agent, resource_name="agent")

    agentic_run = await create_agentic_run(
        session,
        agent_id=agent.id,
        org_id=org_id,
        user_id=current_user.sub,
        title=data.title,
        metadata=data.metadata,
    )
    await session.commit()
    return AgenticRunResponse.model_validate(agentic_run)


@router.get("", response_model=PaginatedResponse)
async def list_agentic_runs_endpoint(
    agent_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-run", "read", "own")),
) -> PaginatedResponse:
    """List agentic runs, optionally filtered by agent (id or slug)."""
    agent_id = await resolve_agent_id_filter(session, agent_id)
    scope_filters = build_scope_filters(current_user, AgenticRun, "agentic-run")
    items, total = await list_agentic_runs(
        session,
        agent_id=agent_id,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
    )
    return PaginatedResponse(
        items=[AgenticRunResponse.model_validate(c) for c in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{agentic_run_id}", response_model=AgenticRunDetail)
async def get_agentic_run_endpoint(
    agentic_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-run", "read", "own")),
) -> AgenticRunDetail:
    """Get an agentic run with all its tasks."""
    agentic_run = await get_agentic_run_with_tasks(session, agentic_run_id)
    check_resource_access(current_user, agentic_run, resource_name="agentic-run")

    base = AgenticRunResponse.model_validate(agentic_run)
    tasks = [AgenticTaskResponse.model_validate(r) for r in agentic_run.tasks]
    return AgenticRunDetail(
        **base.model_dump(),
        tasks=tasks,
    )


@router.patch("/{agentic_run_id}", response_model=AgenticRunResponse)
async def update_agentic_run_endpoint(
    agentic_run_id: str,
    data: AgenticRunUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-run", "execute", "own")),
) -> AgenticRunResponse:
    """Update an agentic run (e.g. rename)."""
    agentic_run = await get_agentic_run(session, agentic_run_id)
    check_resource_access(current_user, agentic_run, resource_name="agentic-run")
    if data.title is not None:
        agentic_run = await update_agentic_run_title(session, agentic_run_id, data.title)
    await session.commit()
    return AgenticRunResponse.model_validate(agentic_run)


@router.delete("/{agentic_run_id}", status_code=204)
async def delete_agentic_run_endpoint(
    agentic_run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-run", "execute", "own")),
) -> None:
    """Delete an agentic run and its tasks."""
    agentic_run = await get_agentic_run(session, agentic_run_id)
    check_resource_access(current_user, agentic_run, resource_name="agentic-run")
    await delete_agentic_run(session, agentic_run_id)
    await session.commit()
