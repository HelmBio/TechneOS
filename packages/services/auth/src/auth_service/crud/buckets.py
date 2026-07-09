"""CRUD operations for ObjectStoreBucket."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.bucket import ObjectStoreBucket
from core.schemas.bucket import BucketCreate, BucketUpdate


async def get_bucket(session: AsyncSession, bucket_id: str) -> ObjectStoreBucket:
    """Get a bucket by ID."""
    result = await session.execute(
        select(ObjectStoreBucket).where(ObjectStoreBucket.id == bucket_id)
    )
    b = result.scalar_one_or_none()
    if b is None:
        raise NotFoundError("ObjectStoreBucket", bucket_id)
    return b


async def get_bucket_by_slug(session: AsyncSession, slug: str) -> ObjectStoreBucket | None:
    """Find a bucket by slug."""
    result = await session.execute(select(ObjectStoreBucket).where(ObjectStoreBucket.slug == slug))
    return result.scalar_one_or_none()


async def create_bucket(
    session: AsyncSession,
    data: BucketCreate,
    org_id: str,
    user_id: str,
    encrypted_access_key: str | None = None,
    encrypted_secret_key: str | None = None,
) -> ObjectStoreBucket:
    """Create a new bucket registration."""
    existing = await get_bucket_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("ObjectStoreBucket", data.slug)

    b = ObjectStoreBucket(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        bucket_name=data.bucket_name,
        endpoint_url=data.endpoint_url,
        region=data.region,
        secure=data.secure,
        encrypted_access_key=encrypted_access_key,
        encrypted_secret_key=encrypted_secret_key,
        is_default=data.is_default,
        org_id=org_id,
        created_by=user_id,
    )
    session.add(b)
    await session.flush()
    await session.refresh(b, ["org", "creator"])
    return b


async def update_bucket(
    session: AsyncSession,
    bucket_id: str,
    data: BucketUpdate,
    user_id: str,
) -> ObjectStoreBucket:
    """Update a bucket registration."""
    b = await get_bucket(session, bucket_id)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(b, field, value)
    await session.flush()
    await session.refresh(b, ["org", "creator"])
    return b


async def delete_bucket(session: AsyncSession, bucket_id: str) -> None:
    """Delete a bucket registration."""
    b = await get_bucket(session, bucket_id)
    await session.delete(b)
    await session.flush()
