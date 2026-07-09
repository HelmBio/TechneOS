"""CRUD operations for notifications."""
import uuid
from typing import cast

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import NotFoundError
from core.models.notification import Notification
from core.schemas.notification import NotificationCreate


async def get_notification(session: AsyncSession, notification_id: str) -> Notification:
    """Get a notification by ID."""
    result = await session.execute(select(Notification).where(Notification.id == notification_id))
    n = result.scalar_one_or_none()
    if n is None:
        raise NotFoundError("Notification", notification_id)
    return n


async def create_notification(session: AsyncSession, data: NotificationCreate) -> Notification:
    """Create a notification."""
    n = Notification(
        id=str(uuid.uuid4()),
        user_id=data.user_id,
        title=data.title,
        message=data.message,
        link=data.link,
        category=data.category,
        source_type=data.source_type,
        source_id=data.source_id,
        is_read=False,
    )
    session.add(n)
    await session.flush()
    return n


async def create_bulk_notifications(
    session: AsyncSession, notifications: list[NotificationCreate]
) -> int:
    """Create notifications in bulk. Returns count created."""
    for data in notifications:
        n = Notification(
            id=str(uuid.uuid4()),
            user_id=data.user_id,
            title=data.title,
            message=data.message,
            link=data.link,
            category=data.category,
            source_type=data.source_type,
            source_id=data.source_id,
            is_read=False,
        )
        session.add(n)
    await session.flush()
    return len(notifications)


async def list_notifications(
    session: AsyncSession,
    user_id: str,
    category: str | None = None,
    is_read: bool | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Notification], int]:
    """List notifications for a user."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    count_stmt = select(func.count(Notification.id)).where(Notification.user_id == user_id)

    if category:
        stmt = stmt.where(Notification.category == category)
        count_stmt = count_stmt.where(Notification.category == category)

    if is_read is not None:
        stmt = stmt.where(Notification.is_read == is_read)
        count_stmt = count_stmt.where(Notification.is_read == is_read)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def unread_count(session: AsyncSession, user_id: str) -> int:
    """Get count of unread notifications."""
    result = await session.execute(
        select(func.count(Notification.id)).where(
            and_(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
    )
    return result.scalar_one()


async def mark_read(session: AsyncSession, notification_id: str) -> Notification:
    """Mark a single notification as read."""
    n = await get_notification(session, notification_id)
    n.is_read = True
    await session.flush()
    return n


async def mark_all_read(session: AsyncSession, user_id: str) -> int:
    """Mark all notifications as read for a user. Returns count updated."""
    result = await session.execute(
        update(Notification)
        .where(and_(Notification.user_id == user_id, Notification.is_read.is_(False)))
        .values(is_read=True)
    )
    await session.flush()
    return cast(int, result.rowcount)  # type: ignore[attr-defined]
