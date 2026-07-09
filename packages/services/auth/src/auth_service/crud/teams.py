"""Team CRUD operations."""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.common import TeamCreate, TeamUpdate
from core.models.user import Org, Team


def _slugify(value: str) -> str:
    """Lowercase, replace non-alphanumeric with hyphens, trim hyphens."""
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s or "team"


async def get_team_by_id(session: AsyncSession, team_id: str) -> Team | None:
    """Find a team by ID."""
    result = await session.execute(select(Team).where(Team.id == team_id))
    return result.scalar_one_or_none()


async def get_team_by_slug(session: AsyncSession, org_id: str, slug: str) -> Team | None:
    """Find a team by (org_id, slug)."""
    result = await session.execute(select(Team).where(Team.org_id == org_id, Team.slug == slug))
    return result.scalar_one_or_none()


async def create_team(session: AsyncSession, org_id: str, data: TeamCreate) -> Team:
    """Create a new team within an organization."""
    # Verify org exists
    result = await session.execute(select(Org).where(Org.id == org_id))
    if result.scalar_one_or_none() is None:
        raise NotFoundError("Organization", org_id)

    slug = data.slug or _slugify(data.name)
    team = Team(
        id=str(uuid.uuid4()),
        name=data.name,
        slug=slug,
        org_id=org_id,
        description=data.description,
    )
    session.add(team)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_teams_org_slug" in str(exc):
            raise AlreadyExistsError("Team", f"slug='{slug}' in org={org_id}") from exc
        raise
    return team


async def update_team(session: AsyncSession, team_id: str, data: TeamUpdate) -> Team:
    """Update an existing team."""
    team = await get_team_by_id(session, team_id)
    if team is None:
        raise NotFoundError("Team", team_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(team, field, value)

    await session.flush()
    return team


async def list_all_teams(session: AsyncSession, skip: int = 0, limit: int = 50) -> list[Team]:
    """List all teams across organizations."""
    result = await session.execute(
        select(Team).offset(skip).limit(limit).order_by(Team.created_at.desc())
    )
    return list(result.scalars().all())


async def count_all_teams(session: AsyncSession) -> int:
    """Count all teams across organizations."""
    result = await session.execute(select(func.count(Team.id)))
    return result.scalar_one()


async def list_teams(
    session: AsyncSession, org_id: str, skip: int = 0, limit: int = 50
) -> list[Team]:
    """List teams within an organization."""
    result = await session.execute(
        select(Team)
        .where(Team.org_id == org_id)
        .offset(skip)
        .limit(limit)
        .order_by(Team.created_at.desc())
    )
    return list(result.scalars().all())


async def count_teams(session: AsyncSession, org_id: str) -> int:
    """Count teams within an organization."""
    result = await session.execute(select(func.count(Team.id)).where(Team.org_id == org_id))
    return result.scalar_one()
