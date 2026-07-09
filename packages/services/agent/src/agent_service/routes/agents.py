"""Agent definition routes — CRUD, search."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.crud.agents import (
    create_agent,
    delete_agent,
    get_agent,
    get_agent_by_slug,
    search_agents,
    update_agent,
)
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.database.postgres import get_async_session
from core.models.agent import AgentDefinition
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from core.utils import is_uuid

router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    """Extract org_id from token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent_endpoint(
    data: AgentCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agent", "create", "*")),
) -> AgentResponse:
    """Create a new agent definition."""
    org_id = _require_org(current_user)
    a = await create_agent(session, data, org_id=org_id, user_id=current_user.sub)
    # Re-query to load relationships (creator, org) for response serialization
    a = await get_agent(session, a.id)

    # Publish event (best-effort, does not block response)
    from agent_service.events import publish_agent_created

    await publish_agent_created(
        agent_id=a.id,
        agent_slug=a.slug,
        agent_name=a.name,
        is_public=a.is_public,
        created_by=current_user.sub,
    )

    return AgentResponse.model_validate(a)


@router.get("", response_model=PaginatedResponse)
async def list_agents_endpoint(
    q: str | None = None,
    tags: list[str] = Query(default=[]),
    skip: int = 0,
    limit: int = 50,
    include_platform: bool = Query(
        default=False, description="Include platform assistant in results"
    ),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agent", "read", "own")),
) -> PaginatedResponse:
    """Search / list agent definitions."""
    scope_filters = build_scope_filters(current_user, AgentDefinition, "agent")
    items, total = await search_agents(
        session,
        q=q,
        tags=tags or None,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
        include_platform=include_platform,
    )
    return PaginatedResponse(
        items=[AgentResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{identifier}", response_model=AgentResponse)
async def get_agent_endpoint(
    identifier: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agent", "read", "own")),
) -> AgentResponse:
    """Get an agent definition. Accepts UUID or slug."""
    if is_uuid(identifier):
        a = await get_agent(session, identifier)
    else:
        _obj = await get_agent_by_slug(session, identifier)
        if _obj is None:
            raise HTTPException(status_code=404, detail=f"Agent '{identifier}' not found")
        a = _obj
    check_resource_access(current_user, a, resource_name="agent")
    return AgentResponse.model_validate(a)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent_endpoint(
    agent_id: str,
    data: AgentUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agent", "update", "own")),
) -> AgentResponse:
    """Update an agent definition."""
    a = await get_agent(session, agent_id)
    check_resource_access(current_user, a, resource_name="agent", write=True)
    a = await update_agent(session, agent_id, data)

    # Publish event (best-effort, does not block response)
    from agent_service.events import publish_agent_updated

    await publish_agent_updated(
        agent_id=a.id,
        agent_slug=a.slug,
        agent_name=a.name,
    )

    return AgentResponse.model_validate(a)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent_endpoint(
    agent_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agent", "delete", "own")),
) -> None:
    """Delete an agent definition and all its runs."""
    a = await get_agent(session, agent_id)
    check_resource_access(current_user, a, resource_name="agent", write=True)
    await delete_agent(session, agent_id)
