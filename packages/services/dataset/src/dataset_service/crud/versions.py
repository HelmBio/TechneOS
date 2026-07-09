"""CRUD operations for dataset versions."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.models.dataset import DatasetVersion


async def get_version(session: AsyncSession, version_id: str) -> DatasetVersion:
    """Get a dataset version by ID."""
    result = await session.execute(select(DatasetVersion).where(DatasetVersion.id == version_id))
    v = result.scalar_one_or_none()
    if v is None:
        raise NotFoundError("DatasetVersion", version_id)
    return v


async def get_version_by_number(
    session: AsyncSession,
    dataset_id: str,
    version_num: int,
) -> DatasetVersion | None:
    """Get a specific version by dataset ID and version number."""
    result = await session.execute(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version == version_num,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(session: AsyncSession, dataset_id: str) -> list[DatasetVersion]:
    """List all versions for a dataset, newest first."""
    result = await session.execute(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version.desc())
    )
    return list(result.scalars().all())


async def next_version_number(session: AsyncSession, dataset_id: str) -> int:
    """Get the next version number for a dataset."""
    result = await session.execute(
        select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == dataset_id)
    )
    current = result.scalar_one_or_none()
    return (current or 0) + 1


async def create_version(
    session: AsyncSession,
    dataset_id: str,
    version_num: int,
    user_id: str,
    storage_bucket: str,
    description: str | None = None,
    files: list[dict[str, Any]] | None = None,
    transfer_method: str | None = None,
    source_bucket_id: str | None = None,
    source_files: list[str] | None = None,
) -> DatasetVersion:
    """Create a new dataset version record."""
    v = DatasetVersion(
        id=str(uuid.uuid4()),
        dataset_id=dataset_id,
        version=version_num,
        description=description,
        storage_bucket=storage_bucket,
        status="uploading",
        created_by=user_id,
        files=files or [],
        transfer_method=transfer_method,
        source_bucket_id=source_bucket_id,
        source_files=source_files,
    )
    session.add(v)
    await session.flush()
    return v


async def update_version_status(
    session: AsyncSession,
    version_id: str,
    status: str,
    user_id: str | None = None,
) -> DatasetVersion:
    """Update version status after processing."""
    v = await get_version(session, version_id)
    v.status = status
    if user_id is not None:
        v.updated_by = user_id
    await session.flush()
    return v


async def delete_version(session: AsyncSession, version_id: str) -> None:
    """Delete a dataset version record."""
    v = await get_version(session, version_id)
    await session.delete(v)
    await session.flush()


async def replace_version_files(
    session: AsyncSession,
    version_id: str,
    files: list[dict[str, Any]],
    user_id: str,
) -> DatasetVersion:
    """Replace all files in a dataset version with new ones."""
    v = await get_version(session, version_id)
    v.files = files
    v.status = "uploading"
    v.updated_by = user_id
    await session.flush()
    return v
