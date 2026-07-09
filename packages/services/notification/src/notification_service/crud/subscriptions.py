"""CRUD operations for subscriptions."""

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AlreadyExistsError, NotFoundError
from core.models.notification import Subscription
from core.schemas.notification import SubscriptionCreate


async def get_subscription(session: AsyncSession, subscription_id: str) -> Subscription:
    """Get a subscription by ID."""
    result = await session.execute(select(Subscription).where(Subscription.id == subscription_id))
    s = result.scalar_one_or_none()
    if s is None:
        raise NotFoundError("Subscription", subscription_id)
    return s


async def check_subscription(
    session: AsyncSession, user_id: str, resource_type: str, resource_id: str
) -> Subscription | None:
    """Check if a user is subscribed to a resource."""
    result = await session.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id == user_id,
                Subscription.resource_type == resource_type,
                Subscription.resource_id == resource_id,
            )
        )
    )
    return result.scalar_one_or_none()


async def create_subscription(
    session: AsyncSession, user_id: str, data: SubscriptionCreate
) -> Subscription:
    """Subscribe a user to a resource."""
    existing = await check_subscription(session, user_id, data.resource_type, data.resource_id)
    if existing is not None:
        raise AlreadyExistsError("Subscription", f"{data.resource_type}:{data.resource_id}")

    s = Subscription(
        id=str(uuid.uuid4()),
        user_id=user_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        preferences=data.preferences,
    )
    session.add(s)
    await session.flush()
    return s


async def delete_subscription(session: AsyncSession, subscription_id: str) -> None:
    """Remove a subscription."""
    s = await get_subscription(session, subscription_id)
    await session.delete(s)
    await session.flush()


async def list_subscriptions(
    session: AsyncSession,
    user_id: str,
    resource_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Subscription], int]:
    """List a user's subscriptions."""
    stmt = select(Subscription).where(Subscription.user_id == user_id)
    count_stmt = select(func.count(Subscription.id)).where(Subscription.user_id == user_id)

    if resource_type:
        stmt = stmt.where(Subscription.resource_type == resource_type)
        count_stmt = count_stmt.where(Subscription.resource_type == resource_type)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(Subscription.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def get_subscribers(
    session: AsyncSession, resource_type: str, resource_id: str
) -> list[Subscription]:
    """Get all subscriptions for a resource (used for notification fanout).

    Returns subscribers for the specific resource **plus** category-level
    subscribers (those with ``resource_id="*"``), with duplicates removed.
    """
    result = await session.execute(
        select(Subscription).where(
            and_(
                Subscription.resource_type == resource_type,
                Subscription.resource_id.in_([resource_id, "*"]),
            )
        )
    )
    subs = list(result.scalars().all())

    # Deduplicate by user_id (prefer the specific subscription)
    seen: dict[str, Subscription] = {}
    for s in subs:
        if s.user_id not in seen or s.resource_id != "*":
            seen[s.user_id] = s
    return list(seen.values())
