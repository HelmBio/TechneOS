"""Notification routes — list, read, mark-all-read, and internal bulk-notify."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.database.postgres import get_async_session
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.notification import (
    BulkNotifyRequest,
    NotificationCreate,
    NotificationResponse,
    UnreadCount,
)
from notification_service.crud.notifications import (
    create_bulk_notifications,
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)
from notification_service.crud.subscriptions import get_subscribers

router = APIRouter()


@router.get("", response_model=PaginatedResponse)
async def list_notifications_endpoint(
    category: str | None = None,
    is_read: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> PaginatedResponse:
    """List the current user's notifications."""
    items, total = await list_notifications(
        session,
        user_id=current_user.sub,
        category=category,
        is_read=is_read,
        skip=skip,
        limit=limit,
    )
    return PaginatedResponse(
        items=[NotificationResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count_endpoint(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> UnreadCount:
    """Get count of unread notifications."""
    count = await unread_count(session, current_user.sub)
    return UnreadCount(count=count)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read_endpoint(
    notification_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> NotificationResponse:
    """Mark a notification as read."""
    n = await mark_read(session, notification_id)
    return NotificationResponse.model_validate(n)


@router.post("/mark-all-read")
async def mark_all_read_endpoint(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, int]:
    """Mark all notifications as read for the current user."""
    count = await mark_all_read(session, current_user.sub)
    return {"marked": count}


# --- Internal endpoint (called by other services) ---


@router.post("/internal/notify", status_code=201)
async def bulk_notify_endpoint(
    data: BulkNotifyRequest,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, int]:
    """Create notifications for all subscribers of a resource.

    This is an internal endpoint called by other services (e.g., tool service)
    when a notable event occurs. It does NOT require user auth — it should be
    called service-to-service behind the gateway.
    """
    subscribers = await get_subscribers(session, data.resource_type, data.resource_id)
    if not subscribers:
        return {"notified": 0}

    notifications = [
        NotificationCreate(
            user_id=sub.user_id,
            title=data.title,
            message=data.message,
            link=data.link,
            category=data.category,
            source_type=data.source_type,
            source_id=data.source_id,
        )
        for sub in subscribers
    ]
    count = await create_bulk_notifications(session, notifications)
    return {"notified": count}
