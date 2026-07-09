"""CRUD operations for pipeline definitions."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions import AlreadyExistsError, ConflictError, NotFoundError, ValidationError
from core.models.pipeline import Pipeline, PipelineRun, PipelineVersion
from core.models.tool import Tool
from core.pipeline_topology import (
    extract_bindings,
    extract_shape,
    fold_default_parameters,
    topology_hash,
)
from core.schemas.pipeline import PipelineCreate, PipelineForkRequest, PipelineUpdate
from pipeline_service.crud.versions import validate_tool_versions


async def get_pipeline(session: AsyncSession, pipeline_id: str) -> Pipeline:
    """Get a pipeline definition by ID."""
    result = await session.execute(
        select(Pipeline)
        .options(
            selectinload(Pipeline.versions).selectinload(PipelineVersion.runs),
            selectinload(Pipeline.versions).selectinload(PipelineVersion.creator),
            selectinload(Pipeline.versions).selectinload(PipelineVersion.updater),
            selectinload(Pipeline.org),
            selectinload(Pipeline.creator),
            selectinload(Pipeline.updater),
        )
        .where(Pipeline.id == pipeline_id)
    )
    p = result.scalar_one_or_none()
    if p is None:
        raise NotFoundError("Pipeline", pipeline_id)
    return p


async def get_pipeline_by_slug(session: AsyncSession, slug: str) -> Pipeline | None:
    """Find a pipeline definition by slug with eager-loaded relationships."""
    result = await session.execute(
        select(Pipeline)
        .options(
            selectinload(Pipeline.versions).selectinload(PipelineVersion.runs),
            selectinload(Pipeline.versions).selectinload(PipelineVersion.creator),
            selectinload(Pipeline.versions).selectinload(PipelineVersion.updater),
            selectinload(Pipeline.org),
            selectinload(Pipeline.creator),
            selectinload(Pipeline.updater),
        )
        .where(Pipeline.slug == slug)
    )
    return result.scalar_one_or_none()


# Tool types eligible for a "compute" pipeline.
_COMPUTE_TOOL_TYPES = frozenset({"pypi", "container"})


def _implied_pipeline_type(tool_types: list[str]) -> str | None:
    """The pipeline type required by a set of step tool types (ADR-aligned rules).

    compute = every tool is pypi/container · interactive = every tool is human ·
    hybrid = any other mix. Returns None when there are no tools to judge.
    """
    if not tool_types:
        return None
    if all(t in _COMPUTE_TOOL_TYPES for t in tool_types):
        return "compute"
    if all(t == "human" for t in tool_types):
        return "interactive"
    return "hybrid"


async def validate_pipeline_type(
    session: AsyncSession, pipeline_type: str, steps: list[dict[str, Any]]
) -> None:
    """Assert the pipeline type matches the kinds of tools in its steps.

    Resolves each step's tool type from the registry and compares against the
    rule-derived type, raising ``ValidationError`` (422) on mismatch. Mirrors the
    create-form check so API/CLI callers (e.g. build_and_register.py) are held to
    the same rule.
    """
    slugs = {s.get("tool_slug") for s in (steps or []) if s.get("tool_slug")}
    if not slugs:
        return
    rows = (
        await session.execute(select(Tool.slug, Tool.tool_type).where(Tool.slug.in_(slugs)))
    ).all()
    type_by_slug = {slug: tool_type for slug, tool_type in rows}
    types = [type_by_slug[s.get("tool_slug")] for s in steps if s.get("tool_slug") in type_by_slug]
    implied = _implied_pipeline_type(types)
    if implied is not None and implied != pipeline_type:
        raise ValidationError(
            f"Pipeline type '{pipeline_type}' does not match its step tools "
            f"({', '.join(sorted(set(types)))}): expected '{implied}'. "
            "Rules: compute = all pypi/container, interactive = all human, "
            "hybrid = any other mix."
        )


async def create_pipeline(
    session: AsyncSession,
    data: PipelineCreate,
    org_id: str,
    user_id: str,
) -> Pipeline:
    """Create a new pipeline definition with an initial active version."""
    existing = await get_pipeline_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("Pipeline", data.slug)

    # Validate that all referenced tool versions are active
    steps_raw = [s.model_dump() for s in data.steps]
    await validate_tool_versions(session, steps_raw)
    # Pipeline type must match the kinds of tools in the DAG.
    await validate_pipeline_type(session, data.pipeline_type, steps_raw)

    # Split the ergonomic inline create into a canonical parent
    # SHAPE (steps without tool_version/parameters, edges, parameters_schema)
    # plus a v1 BINDING ({step_name -> {tool_version, parameters}}).
    edges_raw = [e.model_dump() for e in data.edges]
    shape_steps = extract_shape(steps_raw)
    bindings = extract_bindings(steps_raw)
    # There is no separate default_parameters blob — fold any provided
    # run-input defaults onto the schema as JSON-Schema `default`s.
    schema = fold_default_parameters(data.parameters_schema, data.default_parameters)

    p = Pipeline(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        readme=data.readme,
        category=data.category,
        pipeline_type=data.pipeline_type,
        tags=data.tags,
        is_public=data.is_public,
        steps=shape_steps,
        edges=edges_raw,
        parameters_schema=schema,
        topology_hash=topology_hash(steps_raw, edges_raw, schema),
        org_id=org_id,
        created_by=user_id,
    )
    session.add(p)
    await session.flush()

    # Create the initial version (v1, active) — a binding over the shape.
    v = PipelineVersion(
        id=str(uuid.uuid4()),
        pipeline_id=p.id,
        version=1,
        bindings=bindings,
        status="active",
        changelog="Initial version",
        created_by=user_id,
    )
    session.add(v)
    await session.flush()

    return await get_pipeline(session, p.id)


# Shape fields on PipelineUpdate — editable only while the pipeline has no runs.
_SHAPE_FIELDS = frozenset({"steps", "edges", "parameters_schema"})


async def _pipeline_has_runs(session: AsyncSession, pipeline_id: str) -> bool:
    """Whether any run exists across any version of this pipeline."""
    exists = await session.scalar(
        select(PipelineRun.id)
        .join(PipelineVersion, PipelineRun.version_id == PipelineVersion.id)
        .where(PipelineVersion.pipeline_id == pipeline_id)
        .limit(1)
    )
    return exists is not None


async def update_pipeline(
    session: AsyncSession, pipeline_id: str, data: PipelineUpdate, user_id: str | None = None
) -> Pipeline:
    """Update pipeline metadata, and (only while unused) the canonical shape."""
    p = await get_pipeline(session, pipeline_id)
    update_data = data.model_dump(exclude_unset=True)

    touches_shape = any(
        field in update_data and update_data[field] is not None for field in _SHAPE_FIELDS
    )
    if touches_shape:
        # Shape is immutable once the pipeline has been run.
        if await _pipeline_has_runs(session, pipeline_id):
            raise ConflictError(
                "Pipeline shape is frozen — it has runs. Fork the pipeline to "
                "evolve its topology."
            )
        # Recompute identity from the new shape (validating any tool pins).
        steps_raw = update_data.get("steps", p.steps) or []
        edges_raw = update_data.get("edges", p.edges) or []
        schema = update_data.get("parameters_schema", p.parameters_schema) or {}
        if "steps" in update_data:
            await validate_tool_versions(session, steps_raw)
            update_data["steps"] = extract_shape(steps_raw)
        update_data["topology_hash"] = topology_hash(steps_raw, edges_raw, schema)

    # Re-validate the type ↔ tool-kinds rule whenever the type or shape changes
    # (skipped for metadata-only saves that leave the type untouched, so
    # pipelines predating the rule aren't blocked from unrelated edits).
    type_changed = (
        "pipeline_type" in update_data and update_data["pipeline_type"] != p.pipeline_type
    )
    if type_changed or touches_shape:
        effective_type = update_data.get("pipeline_type", p.pipeline_type)
        effective_steps = update_data.get("steps", p.steps) or []
        await validate_pipeline_type(session, effective_type, effective_steps)

    for field, value in update_data.items():
        setattr(p, field, value)

    if user_id is not None:
        p.updated_by = user_id

    await session.flush()
    return await get_pipeline(session, pipeline_id)


async def fork_pipeline(
    session: AsyncSession,
    pipeline_id: str,
    data: PipelineForkRequest,
    org_id: str,
    user_id: str,
) -> Pipeline:
    """Fork a pipeline: copy the shape into a new pipeline + lineage.

    The fork is the sanctioned way to evolve a pipeline's topology while keeping
    continuity. It starts with a single v1 binding that mirrors the source's
    latest version (or empty bindings if the source has none).
    """
    src = await get_pipeline(session, pipeline_id)

    existing = await get_pipeline_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("Pipeline", data.slug)

    fork = Pipeline(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description if data.description is not None else src.description,
        readme=src.readme,
        category=src.category,
        pipeline_type=src.pipeline_type,
        tags=list(src.tags or []),
        is_public=False,
        steps=list(src.steps or []),
        edges=list(src.edges or []),
        parameters_schema=dict(src.parameters_schema or {}),
        topology_hash=src.topology_hash,
        forked_from=src.id,
        org_id=org_id,
        created_by=user_id,
    )
    session.add(fork)
    await session.flush()

    # Seed v1 from the source's latest version's bindings (if any).
    latest = max(src.versions, key=lambda v: v.version) if src.versions else None
    v = PipelineVersion(
        id=str(uuid.uuid4()),
        pipeline_id=fork.id,
        version=1,
        bindings=dict(latest.bindings or {}) if latest else {},
        status="active",
        changelog=f"Forked from {src.slug}",
        created_by=user_id,
    )
    session.add(v)
    await session.flush()

    return await get_pipeline(session, fork.id)


async def delete_pipeline(session: AsyncSession, pipeline_id: str) -> None:
    """Delete a pipeline definition and all its runs."""
    p = await get_pipeline(session, pipeline_id)
    await session.delete(p)
    await session.flush()


async def list_pipelines(
    session: AsyncSession,
    q: str | None = None,
    is_public: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
) -> tuple[list[Pipeline], int]:
    """List pipeline definitions with optional filters."""
    stmt = select(Pipeline).options(
        selectinload(Pipeline.versions).selectinload(PipelineVersion.runs),
        selectinload(Pipeline.org),
        selectinload(Pipeline.creator),
        selectinload(Pipeline.updater),
    )
    count_stmt = select(func.count(Pipeline.id))

    # Apply scope filters from the route layer
    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if q:
        like = f"%{q}%"
        cond = or_(
            Pipeline.name.ilike(like),
            Pipeline.description.ilike(like),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if is_public is not None:
        stmt = stmt.where(Pipeline.is_public == is_public)
        count_stmt = count_stmt.where(Pipeline.is_public == is_public)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(Pipeline.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
