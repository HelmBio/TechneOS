"""CRUD operations for the compute artifact inventory."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# find_artifact is the shared inventory read helper (also used by agent-service to
# validate agent package_config); it lives in core so both services share it.
from core.database.compute_artifacts import find_artifact  # noqa: F401  — re-exported
from core.exceptions import NotFoundError
from core.models.artifact import ComputeArtifact
from core.schemas.artifact import ArtifactRegister, ArtifactUpdate


async def list_artifacts(
    session: AsyncSession,
    *,
    kind: str | None = None,
    origin: str | None = None,
    status: str | None = None,
    name: str | None = None,
) -> list[ComputeArtifact]:
    """List artifacts, optionally filtered. Newest published first."""
    stmt = select(ComputeArtifact)
    if kind:
        stmt = stmt.where(ComputeArtifact.kind == kind)
    if origin:
        stmt = stmt.where(ComputeArtifact.origin == origin)
    if status:
        stmt = stmt.where(ComputeArtifact.status == status)
    if name:
        # prefix/substring match to power admin-UI autocomplete
        stmt = stmt.where(ComputeArtifact.name.ilike(f"%{name}%"))
    stmt = stmt.order_by(
        ComputeArtifact.name, ComputeArtifact.published_at.desc().nullslast()
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_artifact(session: AsyncSession, artifact_id: str) -> ComputeArtifact:
    result = await session.execute(
        select(ComputeArtifact).where(ComputeArtifact.id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise NotFoundError("ComputeArtifact", artifact_id)
    return artifact


async def register_artifact(
    session: AsyncSession, data: ArtifactRegister, user_id: str | None = None
) -> ComputeArtifact:
    """Idempotent upsert on (kind, name, version, registry_url).

    A new push of the same coordinates refreshes the mutable fields (digest,
    source commit, metadata, published_at) rather than creating a duplicate —
    this matches docker's mutable tags (e.g. ``latest``) while staying a no-op
    refresh for immutable wheel versions.
    """
    registry_match = (
        ComputeArtifact.registry_url.is_(None)
        if data.registry_url is None
        else ComputeArtifact.registry_url == data.registry_url
    )
    result = await session.execute(
        select(ComputeArtifact).where(
            ComputeArtifact.kind == data.kind,
            ComputeArtifact.name == data.name,
            ComputeArtifact.version == data.version,
            registry_match,
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if existing is not None:
        existing.origin = data.origin
        if data.digest is not None:
            existing.digest = data.digest
        if data.size_bytes is not None:
            existing.size_bytes = data.size_bytes
        if data.source_commit_sha is not None:
            existing.source_commit_sha = data.source_commit_sha
        if data.source_repo is not None:
            existing.source_repo = data.source_repo
        if data.metadata:
            existing.metadata_ = data.metadata
        # Re-publishing an artifact that had been retired makes it available again.
        if existing.status == "deleted":
            existing.status = "available"
        existing.published_at = now
        existing.published_by = user_id
        await session.flush()
        return existing

    artifact = ComputeArtifact(
        kind=data.kind,
        origin=data.origin,
        name=data.name,
        version=data.version,
        registry_url=data.registry_url,
        digest=data.digest,
        size_bytes=data.size_bytes,
        source_commit_sha=data.source_commit_sha,
        source_repo=data.source_repo,
        status="available",
        metadata_=data.metadata,
        published_at=now,
        published_by=user_id,
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def update_artifact(
    session: AsyncSession, artifact_id: str, data: ArtifactUpdate
) -> ComputeArtifact:
    artifact = await get_artifact(session, artifact_id)
    if data.status is not None:
        artifact.status = data.status
    if data.metadata is not None:
        artifact.metadata_ = data.metadata
    await session.flush()
    return artifact


async def delete_artifact(session: AsyncSession, artifact_id: str) -> None:
    """Hard-delete a compute artifact record."""
    artifact = await get_artifact(session, artifact_id)
    await session.delete(artifact)
    await session.flush()
