"""Organization CRUD operations."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.common import OrgCreate, OrgUpdate
from core.models.user import Org


async def get_org_by_id(session: AsyncSession, org_id: str) -> Org | None:
    """Find an organization by ID."""
    result = await session.execute(select(Org).where(Org.id == org_id))
    return result.scalar_one_or_none()


async def get_org_by_slug(session: AsyncSession, slug: str) -> Org | None:
    """Find an organization by slug."""
    result = await session.execute(select(Org).where(Org.slug == slug))
    return result.scalar_one_or_none()


async def create_org(session: AsyncSession, data: OrgCreate) -> Org:
    """Create a new organization."""
    existing = await get_org_by_slug(session, data.slug)
    if existing is not None:
        raise AlreadyExistsError("Organization", data.slug)

    org = Org(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=data.slug,
        description=data.description,
        settings=data.settings,
    )
    session.add(org)
    await session.flush()
    return org


async def update_org(session: AsyncSession, org_id: str, data: OrgUpdate) -> Org:
    """Update an existing organization."""
    org = await get_org_by_id(session, org_id)
    if org is None:
        raise NotFoundError("Organization", org_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(org, field, value)

    await session.flush()
    return org


async def list_orgs(session: AsyncSession, skip: int = 0, limit: int = 50) -> list[Org]:
    """List organizations."""
    result = await session.execute(
        select(Org).offset(skip).limit(limit).order_by(Org.created_at.desc())
    )
    return list(result.scalars().all())


async def count_orgs(session: AsyncSession) -> int:
    """Count organizations."""
    result = await session.execute(select(func.count(Org.id)))
    return result.scalar_one()
