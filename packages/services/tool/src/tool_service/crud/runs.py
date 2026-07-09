"""CRUD operations for tool runs and unified artifacts."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.exceptions import NotFoundError, ValidationError
from core.models.tool import Tool, ToolVersion
from core.models.tool_run import ToolRun, ToolRunArtifact
from core.schemas.tool_run import ToolRunUpdate

logger = logging.getLogger(__name__)

TOOL_RUN_BUCKET = "techneos-data"


# ── ToolRun ──────────────────────────────────────────────────────────


async def get_run(session: AsyncSession, run_id: str) -> ToolRun:
    """Get a tool run by ID with eagerly loaded relationships."""
    result = await session.execute(
        select(ToolRun)
        .where(ToolRun.id == run_id)
        .options(
            joinedload(ToolRun.tool_version).joinedload(ToolVersion.tool),
            joinedload(ToolRun.submitter),
            joinedload(ToolRun.org),
        )
    )
    r = result.unique().scalar_one_or_none()
    if r is None:
        raise NotFoundError("ToolRun", run_id)
    return r


async def create_run(
    session: AsyncSession,
    tool_version_id: str,
    parameters: dict[str, Any],
    org_id: str,
    user_id: str,
    restarted_from: str | None = None,
) -> ToolRun:
    """Create a new tool run record."""
    r = ToolRun(
        id=str(uuid.uuid4()),
        tool_version_id=tool_version_id,
        status="pending",
        parameters=parameters,
        outputs={},
        org_id=org_id,
        submitted_by=user_id,
        restarted_from=restarted_from,
    )
    session.add(r)
    await session.flush()
    return r


async def update_run(session: AsyncSession, run_id: str, data: ToolRunUpdate) -> ToolRun:
    """Update a tool run (status, outputs, timing, airflow refs)."""
    r = await get_run(session, run_id)

    # Don't let a late callback overwrite a cancelled run
    if r.status == "cancelled" and "status" in (data.model_fields_set or set()):
        new_status = data.status
        if new_status and new_status != "cancelled":
            logger.warning(
                "Ignoring status update %s -> %s for cancelled run %s",
                r.status, new_status, run_id,
            )
            return r

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(r, field, value)
    await session.flush()
    return r


async def delete_run(session: AsyncSession, run_id: str) -> None:
    """Hard-delete a tool run, its artifacts, and MinIO objects.

    Deletes the run's canonical prefix and any leftover scratch objects
    under the run prefix. DB rows cascade via ``ondelete='CASCADE'`` FKs.
    """
    r = await get_run(session, run_id)
    tool_slug = (r.tool_version.tool.slug if r.tool_version and r.tool_version.tool else "unknown")
    version = (r.tool_version.version if r.tool_version else 0)

    deleted = 0
    try:
        from core.storage import get_object_store

        store = get_object_store()
        bucket = TOOL_RUN_BUCKET
        prefixes = [
            f"tool-runs/{tool_slug}/v{version}/{run_id}/",
            f"scratch-space/tool-runs/{tool_slug}/v{version}/{run_id}/",
        ]
        for prefix in prefixes:
            for obj in store.list_objects(bucket, prefix):
                try:
                    store.delete(bucket, obj.key)
                    deleted += 1
                except Exception as e:
                    logger.warning("Failed to delete object %s: %s", obj.key, e)
    except Exception as e:
        logger.warning("Failed to enumerate MinIO files for run %s: %s", run_id, e)

    await session.delete(r)
    await session.flush()
    logger.info("Deleted tool run %s and %d MinIO object(s)", run_id, deleted)


async def cancel_run(session: AsyncSession, run_id: str) -> ToolRun:
    """Cancel a pending or running tool run."""
    r = await get_run(session, run_id)
    if r.status in ("completed", "failed", "cancelled"):
        raise ValidationError(f"Cannot cancel run in '{r.status}' state")
    r.status = "cancelled"
    r.finished_at = datetime.now(UTC)
    await session.flush()
    return r


async def list_runs(
    session: AsyncSession,
    tool_id: str | None = None,
    tool_version_id: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
    exclude_tool_types: list[str] | None = None,
) -> tuple[list[ToolRun], int]:
    """List tool runs with optional filters."""
    if exclude_tool_types is None:
        exclude_tool_types = ["human"]

    stmt = select(ToolRun).options(
        joinedload(ToolRun.tool_version).joinedload(ToolVersion.tool),
        joinedload(ToolRun.submitter),
        joinedload(ToolRun.org),
    )
    count_stmt = select(func.count(ToolRun.id))

    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if exclude_tool_types:
        sub = (
            select(ToolVersion.id)
            .join(Tool, ToolVersion.tool_id == Tool.id)
            .where(Tool.tool_type.notin_(exclude_tool_types))
        )
        stmt = stmt.where(ToolRun.tool_version_id.in_(sub))
        count_stmt = count_stmt.where(ToolRun.tool_version_id.in_(sub))

    if tool_id:
        sub = select(ToolVersion.id).where(ToolVersion.tool_id == tool_id)
        stmt = stmt.where(ToolRun.tool_version_id.in_(sub))
        count_stmt = count_stmt.where(ToolRun.tool_version_id.in_(sub))

    if tool_version_id:
        stmt = stmt.where(ToolRun.tool_version_id == tool_version_id)
        count_stmt = count_stmt.where(ToolRun.tool_version_id == tool_version_id)

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            stmt = stmt.where(ToolRun.status == statuses[0])
            count_stmt = count_stmt.where(ToolRun.status == statuses[0])
        else:
            stmt = stmt.where(ToolRun.status.in_(statuses))
            count_stmt = count_stmt.where(ToolRun.status.in_(statuses))

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(ToolRun.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.unique().scalars().all()), total


# ── ToolRunArtifact (unified input + output) ────────────────────────


async def create_artifact(
    session: AsyncSession,
    tool_run_id: str,
    io_type: str,
    file_name: str,
    file_size: int,
    content_type: str,
    storage_bucket: str,
    storage_key: str,
    checksum_sha256: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ToolRunArtifact:
    """Create an artifact row (input or output).

    For outputs, dedup by ``(tool_run_id, storage_key)``.
    """
    existing = await session.execute(
        select(ToolRunArtifact).where(
            ToolRunArtifact.tool_run_id == tool_run_id,
            ToolRunArtifact.storage_key == storage_key,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    artifact = ToolRunArtifact(
        id=str(uuid.uuid4()),
        tool_run_id=tool_run_id,
        io_type=io_type,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        checksum_sha256=checksum_sha256,
        storage_bucket=storage_bucket,
        storage_key=storage_key,
        status="active",
        metadata_=metadata or {},
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def get_artifact(session: AsyncSession, artifact_id: str) -> ToolRunArtifact:
    result = await session.execute(select(ToolRunArtifact).where(ToolRunArtifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise NotFoundError("ToolRunArtifact", artifact_id)
    return artifact


async def list_artifacts_for_run(session: AsyncSession, run_id: str) -> list[ToolRunArtifact]:
    result = await session.execute(
        select(ToolRunArtifact)
        .where(ToolRunArtifact.tool_run_id == run_id)
        .order_by(ToolRunArtifact.created_at)
    )
    return list(result.scalars().all())
