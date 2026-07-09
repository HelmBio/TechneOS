"""CRUD operations for agent definitions."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.compute_artifacts import find_artifact
from core.exceptions import AlreadyExistsError, NotFoundError, ValidationError
from core.models.agent import AgentDefinition
from core.schemas.agent import AgentCreate, AgentUpdate
from core.utils import is_uuid


async def _validate_package_config(
    session: AsyncSession, package_config: dict[str, Any] | None
) -> None:
    """Hard-validate an agent's ``package_config`` wheel against the inventory.

    Mirrors the tool-version gate (``tool_service.crud.versions._resolve_artifacts``):
    when ``package_config`` carries ``name`` + ``version``, a matching ``wheel`` row
    with status ``available`` must exist in ``compute_artifacts`` — otherwise the
    agent-service would fail to ``pip install`` it at startup. Skipped when
    ``package_config`` is null or lacks coords (code-baked platform-assistant and
    UI/manually-created agents).
    """
    if not package_config:
        return
    name = package_config.get("name")
    version = package_config.get("version")
    if not name or not version:
        return
    artifact = await find_artifact(session, kind="wheel", name=name, version=version)
    if artifact is None:
        raise ValidationError(
            f"No published wheel '{name}=={version}' found in the artifact "
            "inventory. Build and publish it first (it is recorded via the "
            "compute-artifacts API on publish)."
        )


# The version-relevant slice of an agent definition — the fields that a future
# `agent_versions` row would carry. Keyed by the DB/API names (model_config, not
# the model_config_ attribute alias).
_VERSIONED_FIELDS = (
    "system_prompt",
    "model_config",
    "tools",
    "parameters_schema",
    "default_parameters",
    "package_config",
)


def _definition_snapshot(agent: AgentDefinition) -> dict[str, Any]:
    """The version-relevant slice of ``agent`` (``version``/``captured_at`` added
    by :func:`_append_version_snapshot`)."""
    return {
        "system_prompt": agent.system_prompt,
        "model_config": agent.model_config_,
        "tools": agent.tools,
        "parameters_schema": agent.parameters_schema,
        "default_parameters": agent.default_parameters,
        "package_config": agent.package_config,
    }


def _append_version_snapshot(agent: AgentDefinition) -> None:
    """Append a timestamped definition snapshot to ``agent.version_history``.

    Appends only when a version-relevant field changed since the last entry (always
    on the first call), so metadata-only edits (tags/is_public) don't spam the log.
    Assigns a fresh list so SQLAlchemy persists the JSONB change.
    """
    history = list(agent.version_history or [])
    snap = _definition_snapshot(agent)
    if history and all(snap[f] == history[-1].get(f) for f in _VERSIONED_FIELDS):
        return
    snap["version"] = (history[-1]["version"] + 1) if history else 1
    snap["captured_at"] = datetime.now(UTC).isoformat()
    agent.version_history = [*history, snap]


async def get_agent(session: AsyncSession, agent_id: str) -> AgentDefinition:
    """Get an agent definition by ID, raising NotFoundError if missing."""
    result = await session.execute(select(AgentDefinition).where(AgentDefinition.id == agent_id))
    a = result.scalar_one_or_none()
    if a is None:
        raise NotFoundError("Agent", agent_id)
    return a


async def get_agent_by_slug(session: AsyncSession, slug: str) -> AgentDefinition | None:
    """Find an agent definition by slug."""
    result = await session.execute(select(AgentDefinition).where(AgentDefinition.slug == slug))
    return result.scalar_one_or_none()


async def get_agent_by_id_or_slug(session: AsyncSession, identifier: str) -> AgentDefinition:
    """Resolve an agent by UUID id or slug, raising NotFoundError if missing.

    The web UI navigates agents by slug (``/agents/{slug}``), so user-supplied
    ``agent_id`` values in request bodies may be either form. Mirrors the
    ``GET /agents/{identifier}`` contract.
    """
    if is_uuid(identifier):
        return await get_agent(session, identifier)
    a = await get_agent_by_slug(session, identifier)
    if a is None:
        raise NotFoundError("Agent", identifier)
    return a


async def resolve_agent_id_filter(session: AsyncSession, agent_id: str | None) -> str | None:
    """Normalize an ``agent_id`` list-filter to the canonical UUID.

    Runs/tasks are stored by the agent's UUID, but the web UI filters by slug
    (``/agents/{slug}``). Resolve a slug to its id; leave a UUID — or an unknown
    slug, which then simply matches nothing — untouched. Unlike
    :func:`get_agent_by_id_or_slug` this never raises: filtering on a missing
    agent should yield an empty list, not a 404.
    """
    if not agent_id or is_uuid(agent_id):
        return agent_id
    agent = await get_agent_by_slug(session, agent_id)
    return agent.id if agent is not None else agent_id


async def get_platform_agent(session: AsyncSession) -> AgentDefinition | None:
    """Find the platform agent (is_platform=True)."""
    result = await session.execute(
        select(AgentDefinition).where(AgentDefinition.is_platform.is_(True))
    )
    return result.scalar_one_or_none()


async def create_agent(
    session: AsyncSession,
    data: AgentCreate,
    org_id: str,
    user_id: str,
) -> AgentDefinition:
    """Create a new agent definition."""
    existing = await get_agent_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("Agent", data.slug)

    await _validate_package_config(session, data.package_config)

    a = AgentDefinition(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        agent_type=data.agent_type,
        framework=data.framework,
        system_prompt=data.system_prompt,
        model_config_=data.model_config_,
        tools=data.tools,
        parameters_schema=data.parameters_schema,
        default_parameters=data.default_parameters,
        tags=data.tags,
        is_public=data.is_public,
        is_platform=data.is_platform,
        package_config=data.package_config,
        org_id=org_id,
        created_by=user_id,
    )
    _append_version_snapshot(a)  # seed snapshot version 1
    session.add(a)
    await session.flush()
    return a


async def update_agent(session: AsyncSession, agent_id: str, data: AgentUpdate) -> AgentDefinition:
    """Update agent definition metadata."""
    a = await get_agent(session, agent_id)
    update_data = data.model_dump(exclude_unset=True)

    # org_id is immutable after creation
    update_data.pop("org_id", None)

    # Map the alias field back to the model attribute
    if "model_config_" in update_data:
        update_data["model_config_"] = update_data.pop("model_config_")

    # Gate package_config changes on the artifact inventory (same as create).
    if "package_config" in update_data:
        await _validate_package_config(session, update_data["package_config"])

    for field, value in update_data.items():
        setattr(a, field, value)
    _append_version_snapshot(a)  # records a snapshot iff a versioned field changed
    await session.flush()
    return a


async def delete_agent(session: AsyncSession, agent_id: str) -> None:
    """Delete an agent definition and all its runs."""
    a = await get_agent(session, agent_id)
    await session.delete(a)
    await session.flush()


async def search_agents(
    session: AsyncSession,
    q: str | None = None,
    tags: list[str] | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
    include_platform: bool = False,
) -> tuple[list[AgentDefinition], int]:
    """Search agent definitions with optional filters."""
    stmt = select(AgentDefinition)
    count_stmt = select(func.count(AgentDefinition.id))

    # Exclude platform agents by default
    if not include_platform:
        stmt = stmt.where(AgentDefinition.is_platform == False)  # noqa: E712
        count_stmt = count_stmt.where(AgentDefinition.is_platform == False)  # noqa: E712

    # Apply scope filters from the route layer
    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if q:
        like = f"%{q}%"
        cond = or_(
            AgentDefinition.name.ilike(like),
            AgentDefinition.description.ilike(like),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if tags:
        # Filter agents whose tags JSONB column contains all the requested tags
        for tag in tags:
            cond = AgentDefinition.tags.contains([tag])
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(AgentDefinition.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
