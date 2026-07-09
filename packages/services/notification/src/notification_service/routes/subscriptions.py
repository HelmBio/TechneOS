"""Subscription routes — follow/unfollow resources."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.database.postgres import get_async_session
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.notification import SubscriptionCheck, SubscriptionCreate, SubscriptionResponse
from notification_service.crud.subscriptions import (
    check_subscription,
    create_subscription,
    delete_subscription,
    get_subscription,
    list_subscriptions,
)

router = APIRouter()


@router.post("", response_model=SubscriptionResponse, status_code=201)
async def subscribe_endpoint(
    data: SubscriptionCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> SubscriptionResponse:
    """Subscribe the current user to a resource."""
    s = await create_subscription(session, user_id=current_user.sub, data=data)
    return SubscriptionResponse.model_validate(s)


@router.delete("/{subscription_id}", status_code=204)
async def unsubscribe_endpoint(
    subscription_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Unsubscribe from a resource."""
    s = await get_subscription(session, subscription_id)
    if s.user_id != current_user.sub:
        raise HTTPException(status_code=403, detail="Cannot delete another user's subscription")
    await delete_subscription(session, subscription_id)


@router.get("", response_model=PaginatedResponse)
async def list_subscriptions_endpoint(
    resource_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> PaginatedResponse:
    """List the current user's subscriptions."""
    items, total = await list_subscriptions(
        session,
        user_id=current_user.sub,
        resource_type=resource_type,
        skip=skip,
        limit=limit,
    )
    return PaginatedResponse(
        items=[SubscriptionResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/check", response_model=SubscriptionCheck)
async def check_subscription_endpoint(
    resource_type: str,
    resource_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> SubscriptionCheck:
    """Check if the current user is subscribed to a resource."""
    s = await check_subscription(session, current_user.sub, resource_type, resource_id)
    return SubscriptionCheck(
        subscribed=s is not None,
        subscription_id=s.id if s else None,
    )
