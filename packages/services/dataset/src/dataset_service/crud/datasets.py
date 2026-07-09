"""CRUD operations for datasets."""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.dataset import Dataset
from core.schemas.dataset import DatasetCreate, DatasetSearchParams, DatasetUpdate


async def get_dataset(session: AsyncSession, dataset_id: str) -> Dataset:
    """Get a dataset by ID, raising NotFoundError if missing."""
    result = await session.execute(
        select(Dataset).where(Dataset.id == dataset_id).options(selectinload(Dataset.versions))
    )
    ds = result.scalar_one_or_none()
    if ds is None:
        raise NotFoundError("Dataset", dataset_id)
    return ds


async def get_dataset_by_slug(session: AsyncSession, slug: str) -> Dataset | None:
    """Find a dataset by slug with eager-loaded versions."""
    result = await session.execute(
        select(Dataset).options(selectinload(Dataset.versions)).where(Dataset.slug == slug)
    )
    return result.scalar_one_or_none()


async def create_dataset(
    session: AsyncSession,
    data: DatasetCreate,
    org_id: str,
    user_id: str,
) -> Dataset:
    """Create a new dataset."""
    existing = await get_dataset_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("Dataset", data.slug)

    ds = Dataset(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        data_type=data.data_type,
        file_format=data.file_format,
        tags=data.tags,
        data_schema=data.data_schema,
        metadata_=data.metadata,
        is_public=data.is_public,
        org_id=org_id,
        created_by=user_id,
    )
    session.add(ds)
    await session.flush()
    await session.refresh(ds, attribute_names=["creator", "org", "versions"])
    return ds


async def update_dataset(
    session: AsyncSession,
    dataset_id: str,
    data: DatasetUpdate,
    user_id: str,
) -> Dataset:
    """Update a dataset."""
    ds = await get_dataset(session, dataset_id)
    update_data = data.model_dump(exclude_unset=True)

    # org_id is immutable after creation
    update_data.pop("org_id", None)

    # Map 'metadata' schema field to 'metadata_' ORM field
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")

    for field, value in update_data.items():
        setattr(ds, field, value)

    ds.updated_by = user_id

    await session.flush()
    return ds


async def delete_dataset(session: AsyncSession, dataset_id: str) -> None:
    """Delete a dataset and all its versions."""
    ds = await get_dataset(session, dataset_id)
    await session.delete(ds)
    await session.flush()


async def search_datasets(
    session: AsyncSession,
    params: DatasetSearchParams,
    extra_filters: list[Any] | None = None,
) -> tuple[list[Dataset], int]:
    """Search datasets with filters. Returns (items, total_count)."""
    stmt = select(Dataset)
    count_stmt = select(func.count(Dataset.id))

    # Apply scope filters from the route layer
    for f in extra_filters or []:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    # Apply search filters
    if params.q:
        like = f"%{params.q}%"
        filter_cond = or_(Dataset.name.ilike(like), Dataset.description.ilike(like))
        stmt = stmt.where(filter_cond)
        count_stmt = count_stmt.where(filter_cond)

    if params.data_type:
        stmt = stmt.where(Dataset.data_type == params.data_type)
        count_stmt = count_stmt.where(Dataset.data_type == params.data_type)

    if params.is_public is not None:
        stmt = stmt.where(Dataset.is_public == params.is_public)
        count_stmt = count_stmt.where(Dataset.is_public == params.is_public)

    if params.tags:
        # JSONB array contains any of the tags
        for tag in params.tags:
            stmt = stmt.where(Dataset.tags.contains([tag]))
            count_stmt = count_stmt.where(Dataset.tags.contains([tag]))

    # Get total count
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Get page
    stmt = (
        stmt.options(selectinload(Dataset.versions))
        .order_by(Dataset.created_at.desc())
        .offset(params.skip)
        .limit(params.limit)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    return items, total
