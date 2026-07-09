"""CRUD operations for tool versions."""

import logging
import uuid
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.exceptions import ConflictError, NotFoundError, ValidationError
from core.models.pipeline import PipelineStepRun
from core.models.task_run import TaskRun
from core.models.tool import ContainerConfig, HumanConfig, PypiConfig, ToolVersion
from core.models.tool_run import ToolRun
from core.schemas.tool import (
    ToolVersionContentReplace,
    ToolVersionCreate,
    ToolVersionResponse,
    ToolVersionUpdate,
)
from core.version_lifecycle import definition_editable, validate_status_transition
from tool_service.crud.tools import _resolve_default_assignee

logger = logging.getLogger(__name__)


async def _validate_backend_name(
    session: AsyncSession, resource_requirements: dict[str, Any],
) -> None:
    """Verify that a backend name in resource_requirements is registered and enabled."""
    backend_name = resource_requirements.get("backend")
    if not backend_name:
        return
    from core.models.compute_backend import ComputeBackend

    result = await session.execute(
        select(ComputeBackend).where(ComputeBackend.name == backend_name)
    )
    backend = result.scalar_one_or_none()
    if backend is None:
        raise ValidationError(
            f"Unknown compute backend '{backend_name}'. "
            "Register it via the compute-backends API first."
        )
    if backend.status != "enabled":
        raise ValidationError(
            f"Compute backend '{backend_name}' is not enabled (status: {backend.status})."
        )


async def _resolve_artifacts(session: AsyncSession, data: Any) -> tuple[str | None, str | None]:
    """Hard-validate a version's artifact coordinates against the inventory.

    A pypi version's (package_name, package_version) must match a ``wheel`` row,
    and a container version's (docker_image, docker_tag) must match a
    ``docker_image`` row — both with status ``available``. Raises
    :class:`ValidationError` (→ 422) otherwise so a version can never reference a
    wheel/image that was never built and published.

    Returns ``(pypi_artifact_id, docker_artifact_id)`` for lineage stamping.
    """
    from core.database.compute_artifacts import find_artifact

    pypi_artifact_id: str | None = None
    docker_artifact_id: str | None = None

    if all([data.package_name, data.package_version, data.entry_point]):
        artifact = await find_artifact(
            session,
            kind="wheel",
            name=data.package_name,
            version=data.package_version,
        )
        if artifact is None:
            raise ValidationError(
                f"No published wheel '{data.package_name}=={data.package_version}' "
                "found in the artifact inventory. Build and publish it first "
                "(it is recorded via the compute-artifacts API on publish)."
            )
        pypi_artifact_id = artifact.id

    if data.docker_image:
        docker_tag = data.docker_tag or "latest"
        artifact = await find_artifact(
            session,
            kind="docker_image",
            name=data.docker_image,
            version=docker_tag,
        )
        if artifact is None:
            raise ValidationError(
                f"No published image '{data.docker_image}:{docker_tag}' found in "
                "the artifact inventory. Build and push it first (it is recorded "
                "via the compute-artifacts API on publish)."
            )
        docker_artifact_id = artifact.id

    return pypi_artifact_id, docker_artifact_id


async def tool_version_has_runs(session: AsyncSession, version_id: str) -> bool:
    """Whether any run references this tool version.

    A tool version can be executed standalone (``tool_runs``), as a human
    task (``task_runs``), or as a pipeline step (``pipeline_step_runs``). Any
    of these freezes the version's definition for traceability.
    """
    for model in (ToolRun, TaskRun, PipelineStepRun):
        exists = await session.scalar(
            select(model.id).where(model.tool_version_id == version_id).limit(1)
        )
        if exists is not None:
            return True
    return False


async def tool_versions_with_runs(
    session: AsyncSession, version_ids: list[str]
) -> set[str]:
    """Return the subset of version_ids that have at least one run.

    Batched companion to :func:`tool_version_has_runs` for serialising a list
    of versions without an N+1 query per version.
    """
    if not version_ids:
        return set()
    found: set[str] = set()
    for model in (ToolRun, TaskRun, PipelineStepRun):
        rows = await session.execute(
            select(model.tool_version_id)
            .where(model.tool_version_id.in_(version_ids))
            .distinct()
        )
        found.update(vid for (vid,) in rows.all() if vid is not None)
    return found


async def serialize_tool_versions(
    session: AsyncSession, versions: list[ToolVersion]
) -> list[ToolVersionResponse]:
    """Serialise versions to responses with ``has_runs`` populated in one pass."""
    run_ids = await tool_versions_with_runs(session, [v.id for v in versions])
    out: list[ToolVersionResponse] = []
    for v in versions:
        r = ToolVersionResponse.model_validate(v)
        r.has_runs = v.id in run_ids
        out.append(r)
    return out


async def get_tool_version(session: AsyncSession, version_id: str) -> ToolVersion:
    """Get a tool version by ID with the parent tool eagerly loaded.

    The tool relationship is needed by submit_run for stamping the
    canonical MinIO prefix (tool-runs/{slug}/...) onto input objects
    and onto step_conf. Async sessions can't lazy-load, so we always
    pull the parent tool with the version.
    """
    result = await session.execute(
        select(ToolVersion)
        .where(ToolVersion.id == version_id)
        .options(joinedload(ToolVersion.tool))
    )
    v = result.unique().scalar_one_or_none()
    if v is None:
        raise NotFoundError("ToolVersion", version_id)
    return v


async def list_tool_versions(session: AsyncSession, tool_id: str) -> list[ToolVersion]:
    """List all versions for a tool, newest first."""
    result = await session.execute(
        select(ToolVersion)
        .where(ToolVersion.tool_id == tool_id)
        .order_by(ToolVersion.version.desc())
    )
    return list(result.scalars().all())


async def get_latest_version(session: AsyncSession, tool_id: str) -> ToolVersion | None:
    """Get the latest active version for a tool, with the parent tool eagerly loaded.

    See :func:`get_tool_version` for why eager loading matters.
    """
    result = await session.execute(
        select(ToolVersion)
        .where(ToolVersion.tool_id == tool_id, ToolVersion.status == "active")
        .order_by(ToolVersion.version.desc())
        .options(joinedload(ToolVersion.tool))
        .limit(1)
    )
    return result.unique().scalar_one_or_none()


async def next_version_number(session: AsyncSession, tool_id: str) -> int:
    """Get the next version number for a tool."""
    result = await session.execute(
        select(func.max(ToolVersion.version)).where(ToolVersion.tool_id == tool_id)
    )
    current = result.scalar_one_or_none()
    return (current or 0) + 1


async def create_tool_version(
    session: AsyncSession,
    tool_id: str,
    data: ToolVersionCreate,
    user_id: str,
) -> ToolVersion:
    """Create a new tool version."""
    await _validate_backend_name(session, data.resource_requirements)
    pypi_artifact_id, docker_artifact_id = await _resolve_artifacts(session, data)
    version_num = await next_version_number(session, tool_id)

    v = ToolVersion(
        id=str(uuid.uuid4()),
        tool_id=tool_id,
        version=version_num,
        input_schema=data.input_schema,
        output_schema=data.output_schema,
        parameters_schema=data.parameters_schema,
        resource_requirements=data.resource_requirements,
        changelog=data.changelog,
        status="draft",
        created_by=user_id,
    )
    v.container_config = None
    v.pypi_config = None
    v.human_config = None
    session.add(v)
    await session.flush()

    # Write package config to tool_pypi_configs table
    if all([data.package_name, data.package_version, data.entry_point]):
        pc = PypiConfig(
            tool_version_id=v.id,
            package_name=data.package_name,
            package_version=data.package_version,
            entry_point=data.entry_point,
            package_index_url=data.package_index_url,
            agent_tools=data.agent_tools,
            artifact_id=pypi_artifact_id,
        )
        v.pypi_config = pc
        session.add(pc)

    # Write container config to tool_docker_configs table
    if data.docker_image:
        cc = ContainerConfig(
            tool_version_id=v.id,
            docker_image=data.docker_image,
            docker_tag=data.docker_tag or "latest",
            artifact_id=docker_artifact_id,
        )
        v.container_config = cc
        session.add(cc)

    # Write human config to tool_human_configs table
    if (
        data.assignment_type
        or data.default_assignee
        or data.default_user_email
        or data.default_team_slug
    ):
        assignment_type = data.assignment_type or "team"
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
            due_in_hours=data.due_in_hours,
            require_attachments=data.require_attachments or False,
            priority=data.priority or "medium",
            default_project_lead_email=data.default_project_lead_email,
        )
        v.human_config = hc
        session.add(hc)

    await session.flush()
    return v


async def update_tool_version(
    session: AsyncSession, version_id: str, data: ToolVersionUpdate, user_id: str | None = None
) -> ToolVersion:
    """Update a tool version's metadata fields (status, changelog, etc.)."""
    v = await get_tool_version(session, version_id)
    old_status = v.status

    allowed_fields = {"status", "changelog"}
    update_data = data.model_dump(exclude_unset=True)
    new_status_req = update_data.get("status")
    if new_status_req is not None:
        validate_status_transition(old_status, new_status_req)
    for field, value in update_data.items():
        if field in allowed_fields:
            setattr(v, field, value)
    if user_id:
        v.updated_by = user_id
    await session.flush()

    # Publish event when a version becomes active
    new_status = update_data.get("status")
    if new_status == "active" and old_status != "active":
        try:
            from core.models.tool import Tool
            from tool_service.events import publish_tool_version_active

            tool_result = await session.execute(select(Tool).where(Tool.id == v.tool_id))
            tool = tool_result.scalar_one_or_none()
            if tool:
                await publish_tool_version_active(
                    tool_id=tool.id,
                    tool_slug=tool.slug,
                    tool_name=tool.name,
                    version=v.version,
                )
        except Exception:
            logger.warning("Failed to publish tool.version.active event", exc_info=True)

    return v


async def replace_tool_version_content(
    session: AsyncSession,
    version_id: str,
    data: ToolVersionContentReplace,
    user_id: str,
) -> ToolVersion:
    """Replace a tool version's functional content.

    Resets status to 'draft' since content has changed and requires re-validation.

    Rejected once the version is locked — i.e. it is no longer draft/testing or
    already has recorded runs — to preserve run traceability. Callers must
    create a new version instead.
    """
    v = await get_tool_version(session, version_id)
    if not definition_editable(v.status, await tool_version_has_runs(session, version_id)):
        raise ConflictError(
            f"Tool version v{v.version} is locked (status '{v.status}' or has runs) and "
            "its definition cannot be edited in place. Create a new version instead."
        )
    await _validate_backend_name(session, data.resource_requirements)
    pypi_artifact_id, docker_artifact_id = await _resolve_artifacts(session, data)
    v.input_schema = data.input_schema
    v.output_schema = data.output_schema
    v.parameters_schema = data.parameters_schema
    v.resource_requirements = data.resource_requirements
    v.changelog = data.changelog
    v.status = "draft"
    v.updated_by = user_id
    await session.flush()

    # Replace container config
    if data.docker_image:
        existing = await session.get(ContainerConfig, version_id)
        if existing:
            existing.docker_image = data.docker_image
            existing.docker_tag = data.docker_tag or "latest"
            existing.artifact_id = docker_artifact_id
            v.container_config = existing
        else:
            cc = ContainerConfig(
                tool_version_id=version_id,
                docker_image=data.docker_image,
                docker_tag=data.docker_tag or "latest",
                artifact_id=docker_artifact_id,
            )
            v.container_config = cc
            session.add(cc)
    else:
        existing_cc = await session.get(ContainerConfig, version_id)
        if existing_cc:
            await session.delete(existing_cc)
            v.container_config = None

    # Replace pypi config
    if all([data.package_name, data.package_version, data.entry_point]):
        existing_pc = await session.get(PypiConfig, version_id)
        if existing_pc:
            existing_pc.package_name = cast(str, data.package_name)
            existing_pc.package_version = cast(str, data.package_version)
            existing_pc.entry_point = cast(str, data.entry_point)
            existing_pc.package_index_url = data.package_index_url
            existing_pc.agent_tools = data.agent_tools  # type: ignore[assignment]
            existing_pc.artifact_id = pypi_artifact_id
            v.pypi_config = existing_pc
        else:
            pc = PypiConfig(
                tool_version_id=version_id,
                package_name=data.package_name,
                package_version=data.package_version,
                entry_point=data.entry_point,
                package_index_url=data.package_index_url,
                agent_tools=data.agent_tools,
                artifact_id=pypi_artifact_id,
            )
            v.pypi_config = pc
            session.add(pc)
    else:
        existing_pc = await session.get(PypiConfig, version_id)
        if existing_pc:
            await session.delete(existing_pc)
            v.pypi_config = None

    # Replace human config
    if (
        data.assignment_type
        or data.default_assignee
        or data.default_user_email
        or data.default_team_slug
    ):
        assignment_type = data.assignment_type or "team"
        user_assignee, team_assignee = _resolve_default_assignee(
            assignment_type,
            data.default_user_email,
            data.default_team_slug,
            data.default_assignee,
        )
        existing_hc = await session.get(HumanConfig, version_id)
        if existing_hc:
            existing_hc.assignment_type = assignment_type
            existing_hc.default_user_email = user_assignee
            existing_hc.default_team_slug = team_assignee
            existing_hc.due_in_hours = data.due_in_hours
            existing_hc.require_attachments = data.require_attachments or False
            existing_hc.priority = data.priority or "medium"
            existing_hc.default_project_lead_email = data.default_project_lead_email
            v.human_config = existing_hc
        else:
            hc = HumanConfig(
                tool_version_id=version_id,
                assignment_type=assignment_type,
                default_user_email=user_assignee,
                default_team_slug=team_assignee,
                due_in_hours=data.due_in_hours,
                require_attachments=data.require_attachments or False,
                priority=data.priority or "medium",
                default_project_lead_email=data.default_project_lead_email,
            )
            v.human_config = hc
            session.add(hc)
    else:
        existing_hc = await session.get(HumanConfig, version_id)
        if existing_hc:
            await session.delete(existing_hc)
            v.human_config = None

    await session.flush()
    return v


async def delete_tool_version(session: AsyncSession, version_id: str) -> None:
    """Delete a tool version record."""
    v = await get_tool_version(session, version_id)
    await session.delete(v)
    await session.flush()
