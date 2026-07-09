"""CRUD operations for pipeline versions."""

import uuid
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ConflictError, NotFoundError
from core.models.pipeline import Pipeline, PipelineRun, PipelineVersion
from core.models.tool import Tool, ToolVersion
from core.pipeline_topology import extract_bindings, merge
from core.schemas.pipeline import (
    PipelineVersionCreate,
    PipelineVersionResponse,
    PipelineVersionUpdate,
)
from core.version_lifecycle import definition_editable, validate_status_transition

# Definition fields whose mutation is blocked once a version is locked. Under
# A version's only editable definition is its binding map.
_DEFINITION_FIELDS = frozenset({"bindings"})


async def pipeline_version_has_runs(session: AsyncSession, version_id: str) -> bool:
    """Whether any pipeline run references this version."""
    exists = await session.scalar(
        select(PipelineRun.id).where(PipelineRun.version_id == version_id).limit(1)
    )
    return exists is not None


async def pipeline_versions_with_runs(
    session: AsyncSession, version_ids: list[str]
) -> set[str]:
    """Return the subset of version_ids that have at least one pipeline run."""
    if not version_ids:
        return set()
    rows = await session.execute(
        select(PipelineRun.version_id).where(PipelineRun.version_id.in_(version_ids)).distinct()
    )
    return {vid for (vid,) in rows.all() if vid is not None}


async def serialize_pipeline_versions(
    session: AsyncSession,
    versions: list[PipelineVersion],
    pipeline: Pipeline | None = None,
) -> list[PipelineVersionResponse]:
    """Serialise versions with ``has_runs`` and effective DAG populated.

    The response exposes both the raw ``bindings`` and a computed
    effective DAG (parent **shape** merged with the version's bindings) so the
    run dialog/graph keep working. The parent shape is read from ``pipeline`` if
    given, else from each version's loaded ``pipeline`` backref.
    """
    run_ids = await pipeline_versions_with_runs(session, [v.id for v in versions])
    out: list[PipelineVersionResponse] = []
    for v in versions:
        parent = pipeline or v.pipeline
        r = PipelineVersionResponse.model_validate(v)
        r.has_runs = v.id in run_ids
        r.steps = merge(parent.steps or [], v.bindings or {}) if parent else []
        r.edges = list(parent.edges or []) if parent else []
        r.parameters_schema = dict(parent.parameters_schema or {}) if parent else {}
        out.append(r)

    # Attach each step's pinned tool-version parameters_schema (read-only) so the
    # run dialog can build typed forms; the binding's parameter keys/values
    # project which fields to show and their defaults (PR1 of step-param-schema).
    await attach_step_tool_schemas(session, [r.steps for r in out])
    return out


async def attach_step_tool_schemas(
    session: AsyncSession,
    step_lists: list[list[dict[str, Any]]],
) -> None:
    """Resolve and attach ``parameters_schema`` to each effective step in place.

    For every step the schema is read from its pinned tool version (``tool_slug``
    + ``tool_version``; when ``tool_version`` is null, the latest active version).
    Batched into two queries (tools by slug, then their versions) regardless of
    how many versions/steps are passed. The schema is the tool version's — it is
    never stored on the binding, only surfaced for form-building.
    """
    needed: set[tuple[str, int | None]] = set()
    for steps in step_lists:
        for st in steps:
            slug = st.get("tool_slug")
            if slug:
                needed.add((slug, st.get("tool_version")))
    if not needed:
        return

    slugs = {slug for slug, _ in needed}
    tools = (await session.execute(select(Tool).where(Tool.slug.in_(slugs)))).scalars().all()
    tool_by_slug = {t.slug: t for t in tools}
    tool_ids = [t.id for t in tools]

    versions_by_tool: dict[str, list[ToolVersion]] = {}
    if tool_ids:
        tvs = (
            await session.execute(select(ToolVersion).where(ToolVersion.tool_id.in_(tool_ids)))
        ).scalars().all()
        for tv in tvs:
            versions_by_tool.setdefault(tv.tool_id, []).append(tv)

    schema_by_key: dict[tuple[str, int | None], dict[str, Any]] = {}
    for slug, ver in needed:
        tool = tool_by_slug.get(slug)
        chosen: ToolVersion | None = None
        if tool is not None:
            tvs = versions_by_tool.get(tool.id, [])
            if ver is not None:
                chosen = next((tv for tv in tvs if tv.version == ver), None)
            if chosen is None:
                pool = [tv for tv in tvs if tv.status == "active"] or tvs
                chosen = max(pool, key=lambda tv: tv.version) if pool else None
        schema_by_key[(slug, ver)] = (chosen.parameters_schema if chosen else {}) or {}

    for steps in step_lists:
        for st in steps:
            slug = st.get("tool_slug")
            if slug:
                st["parameters_schema"] = schema_by_key.get((slug, st.get("tool_version")), {})


async def serialize_pipeline_version(
    session: AsyncSession,
    version: PipelineVersion,
    pipeline: Pipeline | None = None,
) -> PipelineVersionResponse:
    """Serialise a single version (effective DAG + ``has_runs``)."""
    [resp] = await serialize_pipeline_versions(session, [version], pipeline=pipeline)
    return resp


async def validate_tool_versions(
    session: AsyncSession,
    steps: list[dict[str, Any]],
) -> None:
    """Validate that every step references an active tool version, and
    **pin** unpinned steps to the currently-active version number.

    A step that arrives with ``tool_version=None`` (or 0, or
    missing) is mutated in place to set ``tool_version`` to the tool's
    current latest-active version number. The pipeline version row that
    gets persisted therefore always carries a concrete number, so an
    unrelated tool activation can't silently change a saved pipeline's
    behaviour.

    Steps that *opt out* of pinning by setting ``track_latest: true``
    keep ``tool_version=None`` — the orchestrator continues to resolve
    "latest active" at dispatch time. Use sparingly; the platform
    sends a notification when a newer version of a tool you depend
    on activates so most users can pin explicitly and bump on demand.

    Raises HTTPException 400 if any step references a non-active version
    or if the requested version number does not exist.
    """
    for step in steps:
        tool_slug = step.get("tool_slug")
        if not tool_slug:
            continue

        requested_version = step.get("tool_version")
        track_latest = bool(step.get("track_latest", False))

        # Fetch tool by slug.
        tool_result = await session.execute(select(Tool).where(Tool.slug == tool_slug))
        tool = tool_result.scalar_one_or_none()
        if not tool:
            raise HTTPException(
                status_code=400,
                detail=f"Tool with slug '{tool_slug}' not found",
            )

        if requested_version:
            # Specific version requested — must be active.
            version_result = await session.execute(
                select(ToolVersion).where(
                    ToolVersion.tool_id == tool.id,
                    ToolVersion.version == int(requested_version),
                )
            )
            tv = version_result.scalar_one_or_none()
            if not tv:
                raise HTTPException(
                    status_code=400,
                    detail=f"Tool '{tool_slug}' version {requested_version} not found",
                )
            if tv.status != "active":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Tool '{tool_slug}' version {requested_version} is "
                        f"'{tv.status}' — only 'active' versions can be used "
                        "in pipelines"
                    ),
                )
            # Already pinned to a concrete number; nothing more to do.
            continue

        # Unpinned step ("latest active") — look it up.
        active_result = await session.execute(
            select(ToolVersion)
            .where(
                ToolVersion.tool_id == tool.id,
                ToolVersion.status == "active",
            )
            .order_by(ToolVersion.version.desc())
            .limit(1)
        )
        latest_active = active_result.scalar_one_or_none()
        if latest_active is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Tool '{tool_slug}' has no active version — only "
                    "'active' versions can be used in pipelines"
                ),
            )

        if not track_latest:
            # Pin: record the resolved version number so reruns reproduce.
            step["tool_version"] = latest_active.version
        # If track_latest: leave tool_version unset; orchestrator resolves on dispatch.


async def get_pipeline_version(session: AsyncSession, version_id: str) -> PipelineVersion:
    """Get a pipeline version by ID."""
    result = await session.execute(select(PipelineVersion).where(PipelineVersion.id == version_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise NotFoundError("PipelineVersion", version_id)
    return v


async def list_pipeline_versions(
    session: AsyncSession, pipeline_id: str
) -> list[PipelineVersion]:
    """List all versions for a pipeline, newest first."""
    result = await session.execute(
        select(PipelineVersion)
        .where(PipelineVersion.pipeline_id == pipeline_id)
        .order_by(PipelineVersion.version.desc())
    )
    return list(result.scalars().all())


async def get_latest_active_version(
    session: AsyncSession, pipeline_id: str
) -> PipelineVersion | None:
    """Get the latest active version for a pipeline."""
    result = await session.execute(
        select(PipelineVersion)
        .where(
            PipelineVersion.pipeline_id == pipeline_id,
            PipelineVersion.status == "active",
        )
        .order_by(PipelineVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def next_version_number(session: AsyncSession, pipeline_id: str) -> int:
    """Get the next version number for a pipeline."""
    result = await session.execute(
        select(func.max(PipelineVersion.version)).where(
            PipelineVersion.pipeline_id == pipeline_id
        )
    )
    current = result.scalar_one_or_none()
    return (current or 0) + 1


def _bindings_from_create(data: PipelineVersionCreate) -> dict[str, dict[str, Any]]:
    """Resolve the binding map from a create payload (preferred or legacy form)."""
    if data.bindings is not None:
        return {
            name: {
                "tool_version": b.get("tool_version"),
                "parameters": b.get("parameters") or {},
            }
            for name, b in data.bindings.items()
        }
    if data.steps is not None:
        steps_raw = [s.model_dump() if hasattr(s, "model_dump") else s for s in data.steps]
        return extract_bindings(cast("list[dict[str, Any]]", steps_raw))
    return {}


async def _validate_binding_param_keys(
    session: AsyncSession,
    effective_steps: list[dict[str, Any]],
    bindings: dict[str, dict[str, Any]],
) -> None:
    """Assert each binding only sets parameters that exist in the tool schema.

    The binding *projects* which tool-version parameters to expose at run time
    (PR2 of step-param-schema), so a binding key that isn't a property of the
    pinned tool version's ``parameters_schema`` is a mistake (e.g. a typo, or a
    re-pin that dropped the parameter). Only enforced when the tool version
    actually declares properties.
    """
    await attach_step_tool_schemas(session, [effective_steps])
    for step in effective_steps:
        name = step.get("name")
        params = (bindings.get(cast(str, name)) or {}).get("parameters") or {}
        props = (step.get("parameters_schema") or {}).get("properties") or {}
        if not props:
            continue
        unknown = set(params) - set(props)
        if unknown:
            raise ConflictError(
                f"Step '{name}' binds parameters not in tool '{step.get('tool_slug')}' "
                f"v{step.get('tool_version')}: {', '.join(sorted(unknown))}."
            )


async def create_pipeline_version(
    session: AsyncSession,
    pipeline_id: str,
    data: PipelineVersionCreate,
    user_id: str,
) -> PipelineVersion:
    """Create a new version — a binding over the pipeline's fixed shape."""
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise NotFoundError("Pipeline", pipeline_id)

    bindings = _bindings_from_create(data)

    # The binding may only target steps that exist in the pipeline's shape —
    # versions cannot add/remove/rewire steps (that would be a fork).
    shape_names = {s.get("name") for s in (pipeline.steps or [])}
    unknown = set(bindings) - shape_names
    if unknown:
        raise ConflictError(
            "Binding references steps not in the pipeline shape "
            f"({', '.join(sorted(unknown))}). Changing the topology requires a fork."
        )

    # Validate tool versions against the effective (merged) steps and capture
    # any pinning the validator applies back onto the bindings.
    effective = merge(pipeline.steps or [], bindings)
    await validate_tool_versions(session, effective)
    for step in effective:
        name = step.get("name")
        if name in bindings:
            bindings[name]["tool_version"] = step.get("tool_version")

    # Bindings may only set parameters declared by the pinned tool version.
    await _validate_binding_param_keys(session, effective, bindings)

    version_num = await next_version_number(session, pipeline_id)

    v = PipelineVersion(
        id=str(uuid.uuid4()),
        pipeline_id=pipeline_id,
        version=version_num,
        bindings=bindings,
        changelog=data.changelog,
        status="draft",
        created_by=user_id,
    )
    session.add(v)
    await session.flush()
    return v


async def update_pipeline_version(
    session: AsyncSession,
    version_id: str,
    data: PipelineVersionUpdate,
    user_id: str | None = None,
) -> PipelineVersion:
    """Update a pipeline version (status, DAG, etc.)."""
    v = await get_pipeline_version(session, version_id)
    update_data = data.model_dump(exclude_unset=True)

    # Validate status transition against the shared lifecycle policy.
    new_status_req = update_data.get("status")
    if new_status_req is not None:
        validate_status_transition(v.status, new_status_req)

    # Block in-place binding edits once the version is locked (no longer
    # draft/testing, or already has runs) to preserve run traceability.
    touches_definition = any(
        field in update_data and update_data[field] is not None for field in _DEFINITION_FIELDS
    )
    if touches_definition and not definition_editable(
        v.status, await pipeline_version_has_runs(session, version_id)
    ):
        raise ConflictError(
            f"Pipeline version v{v.version} is locked (status '{v.status}' or has runs) and "
            "its binding cannot be edited in place. Create a new version instead."
        )

    # Re-validate tool versions when the binding changes, against the parent shape.
    if update_data.get("bindings") is not None:
        pipeline = await session.get(Pipeline, v.pipeline_id)
        shape_steps = pipeline.steps if pipeline else []
        shape_names = {s.get("name") for s in (shape_steps or [])}
        unknown = set(update_data["bindings"]) - shape_names
        if unknown:
            raise ConflictError(
                "Binding references steps not in the pipeline shape "
                f"({', '.join(sorted(unknown))}). Changing the topology requires a fork."
            )
        effective = merge(shape_steps or [], update_data["bindings"])
        await validate_tool_versions(session, effective)
        await _validate_binding_param_keys(session, effective, update_data["bindings"])

    for field, value in update_data.items():
        setattr(v, field, value)

    if user_id is not None:
        v.updated_by = user_id

    await session.flush()
    return v


async def delete_pipeline_version(session: AsyncSession, version_id: str) -> None:
    """Delete a pipeline version and all its runs (cascaded)."""
    v = await get_pipeline_version(session, version_id)
    await session.delete(v)
    await session.flush()
