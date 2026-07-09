"""CRUD operations for tools."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.tool import HumanConfig, Tool, ToolVersion
from core.schemas.tool import ToolCreate, ToolUpdate


def _resolve_default_assignee(
    assignment_type: str,
    default_user_email: str | None,
    default_team_slug: str | None,
    default_assignee_legacy: str | None,
) -> tuple[str | None, str | None]:
    """Resolve the (email, team_slug) pair from the new split fields plus
    the legacy single-string ``default_assignee``.

    Explicit ``default_user_email`` / ``default_team_slug`` win; the legacy
    field is only used as fallback and routed by ``assignment_type``.
    """
    if default_user_email or default_team_slug:
        return default_user_email, default_team_slug
    if not default_assignee_legacy:
        return None, None
    if assignment_type == "user":
        return default_assignee_legacy, None
    return None, default_assignee_legacy


async def get_tool(session: AsyncSession, tool_id: str) -> Tool:
    """Get a tool by ID, raising NotFoundError if missing."""
    result = await session.execute(
        select(Tool).options(selectinload(Tool.versions)).where(Tool.id == tool_id)
    )
    t = result.scalar_one_or_none()
    if t is None:
        raise NotFoundError("Tool", tool_id)
    return t


async def get_tool_by_slug(session: AsyncSession, slug: str) -> Tool | None:
    """Find a tool by slug."""
    result = await session.execute(
        select(Tool).where(Tool.slug == slug).options(selectinload(Tool.versions))
    )
    return result.scalar_one_or_none()


async def create_tool(
    session: AsyncSession,
    data: ToolCreate,
    org_id: str,
    user_id: str,
) -> Tool:
    """Register a new tool.

    For ``tool_type="human"``, the first version is auto-created when
    human config fields are provided.
    """
    existing = await get_tool_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("Tool", data.slug)

    t = Tool(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        category=data.category,
        tool_type=data.tool_type,
        tags=data.tags,
        is_public=data.is_public,
        readme=data.readme,
        org_id=org_id,
        created_by=user_id,
    )
    session.add(t)
    await session.flush()

    # Auto-create the first version for human-type tools
    if data.tool_type == "human" and (
        data.assignment_type
        or data.default_assignee
        or data.default_user_email
        or data.default_team_slug
    ):
        v = ToolVersion(
            id=str(uuid.uuid4()),
            tool_id=t.id,
            version=1,
            status="active",
            input_schema=data.input_schema,
            output_schema=data.output_schema,
            parameters_schema=data.parameters_schema,
            resource_requirements={},
            created_by=user_id,
        )
        session.add(v)
        await session.flush()

        assignment_type = data.assignment_type or "user"
        user_assignee, team_assignee = _resolve_default_assignee(
            assignment_type,
            data.default_user_email,
            data.default_team_slug,
            data.default_assignee,
        )
        hc = HumanConfig(
            tool_version_id=v.id,
            assignment_type=assignment_type,
            default_user_email=user_assignee,
            default_team_slug=team_assignee,
            due_in_hours=data.due_in_hours or 72,
            require_attachments=data.require_attachments or False,
            default_project_lead_email=data.default_project_lead_email,
        )
        v.human_config = hc
        session.add(hc)
        await session.flush()

    # Eagerly load relationships so @property accessors work outside async context
    await session.refresh(t, attribute_names=["creator", "org", "versions"])
    return t


async def update_tool(
    session: AsyncSession, tool_id: str, data: ToolUpdate, user_id: str | None = None
) -> Tool:
    """Update tool metadata."""
    t = await get_tool(session, tool_id)
    update_data = data.model_dump(exclude_unset=True)
    # org_id is immutable after creation
    update_data.pop("org_id", None)
    for field, value in update_data.items():
        setattr(t, field, value)
    if user_id:
        t.updated_by = user_id
    await session.flush()
    await session.refresh(t, attribute_names=["creator", "updater", "org", "versions"])
    return t


async def delete_tool(session: AsyncSession, tool_id: str) -> None:
    """Delete a tool and all its versions."""
    t = await get_tool(session, tool_id)
    await session.delete(t)
    await session.flush()


async def list_tools(
    session: AsyncSession,
    q: str | None = None,
    category: str | None = None,
    tool_type: str | None = None,
    is_public: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
) -> tuple[list[Tool], int]:
    """List tools with optional filters."""
    stmt = select(Tool).options(selectinload(Tool.versions))
    count_stmt = select(func.count(Tool.id))

    # Apply scope filters from the route layer
    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if q:
        like = f"%{q}%"
        cond = or_(Tool.name.ilike(like), Tool.description.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if category:
        stmt = stmt.where(Tool.category == category)
        count_stmt = count_stmt.where(Tool.category == category)

    if tool_type:
        stmt = stmt.where(Tool.tool_type == tool_type)
        count_stmt = count_stmt.where(Tool.tool_type == tool_type)
    else:
        stmt = stmt.where(Tool.tool_type != "human")
        count_stmt = count_stmt.where(Tool.tool_type != "human")

    if is_public is not None:
        stmt = stmt.where(Tool.is_public == is_public)
        count_stmt = count_stmt.where(Tool.is_public == is_public)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(Tool.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
