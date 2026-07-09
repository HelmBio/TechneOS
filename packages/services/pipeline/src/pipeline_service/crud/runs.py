"""CRUD operations for pipeline runs and step runs."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.exceptions import NotFoundError
from core.models.pipeline import (
    PipelineRun,
    PipelineRunArtifact,
    PipelineStepRun,
    PipelineVersion,
)
from core.schemas.pipeline import PipelineRunUpdate

logger = logging.getLogger(__name__)

# Bucket convention mirrors datasets/tool-runs — single platform-data bucket.
PIPELINE_RUN_BUCKET = "techneos-data"


async def get_run(session: AsyncSession, run_id: str) -> PipelineRun:
    """Get a pipeline run by ID with eagerly loaded relationships."""
    result = await session.execute(
        select(PipelineRun)
        .where(PipelineRun.id == run_id)
        .options(
            joinedload(PipelineRun.version).joinedload(PipelineVersion.pipeline),
            joinedload(PipelineRun.submitter),
            joinedload(PipelineRun.org),
        )
    )
    r = result.unique().scalar_one_or_none()
    if r is None:
        raise NotFoundError("PipelineRun", run_id)
    return r


async def create_run(
    session: AsyncSession,
    version_id: str,
    parameters: dict[str, Any],
    org_id: str,
    user_id: str,
    restarted_from: str | None = None,
    name: str | None = None,
) -> PipelineRun:
    """Create a new pipeline run."""
    r = PipelineRun(
        id=str(uuid.uuid4()),
        version_id=version_id,
        status="pending",
        parameters=parameters,
        org_id=org_id,
        submitted_by=user_id,
        restarted_from=restarted_from,
        name=name,
    )
    session.add(r)
    await session.flush()
    return r


async def update_run(session: AsyncSession, run_id: str, data: PipelineRunUpdate) -> PipelineRun:
    """Update a pipeline run (status, timing, airflow refs)."""
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
    """Hard-delete a pipeline run, its artifacts, and MinIO objects.

    Deletes the run's canonical prefix (step outputs under ``{step_name}/``
    and inputs under ``inputs/``) and any leftover scratch objects under the
    run prefix. DB rows (step runs, artifacts) cascade via ``ondelete=CASCADE``.
    """
    r = await get_run(session, run_id)
    slug = r.version.pipeline.slug if r.version and r.version.pipeline else "unknown"
    version = r.version.version if r.version else 0

    deleted = 0
    try:
        from core.storage import get_object_store

        store = get_object_store()
        prefixes = [
            f"pipeline-runs/{slug}/v{version}/{run_id}/",
            f"scratch-space/pipeline-runs/{slug}/v{version}/{run_id}/",
        ]
        for prefix in prefixes:
            for obj in store.list_objects(PIPELINE_RUN_BUCKET, prefix):
                try:
                    store.delete(PIPELINE_RUN_BUCKET, obj.key)
                    deleted += 1
                except Exception as e:
                    logger.warning("Failed to delete object %s: %s", obj.key, e)
    except Exception as e:
        logger.warning("Failed to enumerate MinIO files for run %s: %s", run_id, e)

    await session.delete(r)
    await session.flush()
    logger.info("Deleted pipeline run %s and %d MinIO object(s)", run_id, deleted)


async def cancel_run(session: AsyncSession, run_id: str) -> PipelineRun:
    """Cancel a pending or running pipeline run."""
    r = await get_run(session, run_id)
    if r.status in ("completed", "failed", "cancelled"):
        from core.exceptions import ValidationError

        raise ValidationError(f"Cannot cancel run in '{r.status}' state")
    r.status = "cancelled"
    r.finished_at = datetime.now(UTC)
    await session.flush()
    return r


async def list_runs(
    session: AsyncSession,
    pipeline_id: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    extra_filters: list[Any] | None = None,
) -> tuple[list[PipelineRun], int]:
    """List pipeline runs with filters."""
    stmt = select(PipelineRun).options(
        joinedload(PipelineRun.version).joinedload(PipelineVersion.pipeline),
        joinedload(PipelineRun.submitter),
        joinedload(PipelineRun.org),
    )
    count_stmt = select(func.count(PipelineRun.id))

    # Apply scope filters from the route layer
    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    if pipeline_id:
        # Filter runs by pipeline definition (through version)
        stmt = stmt.where(
            PipelineRun.version_id.in_(
                select(PipelineVersion.id).where(PipelineVersion.pipeline_id == pipeline_id)
            )
        )
        count_stmt = count_stmt.where(
            PipelineRun.version_id.in_(
                select(PipelineVersion.id).where(PipelineVersion.pipeline_id == pipeline_id)
            )
        )

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            stmt = stmt.where(PipelineRun.status == statuses[0])
            count_stmt = count_stmt.where(PipelineRun.status == statuses[0])
        else:
            stmt = stmt.where(PipelineRun.status.in_(statuses))
            count_stmt = count_stmt.where(PipelineRun.status.in_(statuses))

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(PipelineRun.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.unique().scalars().all()), total


# --- Step runs ---


async def get_step_runs(session: AsyncSession, run_id: str) -> list[PipelineStepRun]:
    """Get all step runs for a pipeline run."""
    result = await session.execute(
        select(PipelineStepRun)
        .where(PipelineStepRun.run_id == run_id)
        .order_by(PipelineStepRun.created_at)
    )
    return list(result.scalars().all())


async def create_step_run(
    session: AsyncSession,
    run_id: str,
    step_name: str,
    tool_version_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> PipelineStepRun:
    """Create a step run record."""
    sr = PipelineStepRun(
        id=str(uuid.uuid4()),
        run_id=run_id,
        step_name=step_name,
        tool_version_id=tool_version_id,
        status="pending",
        parameters=parameters or {},
    )
    session.add(sr)
    await session.flush()
    return sr


async def update_step_run(
    session: AsyncSession,
    step_run_id: str,
    status: str | None = None,
    outputs: dict[str, Any] | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> PipelineStepRun:
    """Update a step run's status and outputs."""
    result = await session.execute(select(PipelineStepRun).where(PipelineStepRun.id == step_run_id))
    sr = result.scalar_one_or_none()
    if sr is None:
        raise NotFoundError("PipelineStepRun", step_run_id)

    if status is not None:
        sr.status = status
    if outputs is not None:
        sr.outputs = outputs
    if error_message is not None:
        sr.error_message = error_message
    if started_at is not None:
        sr.started_at = started_at
    if finished_at is not None:
        sr.finished_at = finished_at

    await session.flush()
    return sr


async def update_step_run_by_name(
    session: AsyncSession,
    run_id: str,
    step_name: str,
    status: str | None = None,
    outputs: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> PipelineStepRun:
    """Update a step run looked up by run_id + step_name.

    Used by the Airflow callback endpoint which identifies steps by name
    rather than by internal id.
    """
    result = await session.execute(
        select(PipelineStepRun).where(
            PipelineStepRun.run_id == run_id,
            PipelineStepRun.step_name == step_name,
        )
    )
    sr = result.scalar_one_or_none()
    if sr is None:
        # Auto-create the step run record.  This handles cases where the
        # Airflow DAG reports status for a step that wasn't pre-created
        # (e.g. dynamically added steps, or name mismatches between the
        # pipeline definition and the Airflow conf).
        sr = PipelineStepRun(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_name=step_name,
            status="pending",
            parameters={},
        )
        session.add(sr)

    now = datetime.now(UTC)

    if status is not None:
        sr.status = status
        if status == "running" and sr.started_at is None:
            sr.started_at = now
        if status in ("completed", "failed", "skipped") and sr.finished_at is None:
            sr.finished_at = now
    if outputs is not None:
        sr.outputs = outputs
    if error_message is not None:
        sr.error_message = error_message

    await session.flush()
    return sr


# ── Artifacts ───────────────────────────────────────────────────────


async def create_artifact(
    session: AsyncSession,
    run_id: str,
    step_name: str | None,
    name: str,
    artifact_type: str,
    file_name: str,
    file_size: int,
    content_type: str,
    checksum_sha256: str | None,
    storage_bucket: str,
    storage_key: str,
    io_type: str = "output",
    metadata: dict[str, Any] | None = None,
) -> "PipelineRunArtifact":
    """Create a run artifact record (or return existing if duplicate)."""
    from sqlalchemy import select


    # Deduplicate: if an artifact with the same run + storage key exists, return it
    existing = await session.execute(
        select(PipelineRunArtifact).where(
            PipelineRunArtifact.run_id == run_id,
            PipelineRunArtifact.storage_key == storage_key,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    artifact = PipelineRunArtifact(
        run_id=run_id,
        io_type=io_type,
        step_name=step_name,
        name=name,
        artifact_type=artifact_type,
        file_name=file_name,
        file_size=file_size,
        content_type=content_type,
        checksum_sha256=checksum_sha256,
        storage_bucket=storage_bucket,
        storage_key=storage_key,
        metadata_=metadata or {},
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def get_artifact(session: AsyncSession, artifact_id: str) -> "PipelineRunArtifact":
    """Get a single artifact by ID."""

    result = await session.execute(select(PipelineRunArtifact).where(PipelineRunArtifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise NotFoundError("PipelineRunArtifact", artifact_id)
    return artifact
