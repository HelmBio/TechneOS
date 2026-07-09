"""Pydantic schemas for subscriptions and notifications."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema

# --- Subscription ---


class SubscriptionCreate(BaseModel):
    resource_type: str = Field(min_length=1, max_length=50)
    resource_id: str = Field(min_length=1, max_length=36)
    preferences: dict[str, Any] = Field(default_factory=dict)


class SubscriptionResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    resource_type: str
    resource_id: str
    preferences: dict[str, Any]


class SubscriptionCheck(BaseModel):
    subscribed: bool
    subscription_id: str | None = None


# --- Notification ---


class NotificationCreate(BaseModel):
    """Internal schema for creating notifications (used by services, not exposed via API)."""

    user_id: str
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1)
    link: str | None = None
    category: str = Field(default="general", max_length=50)
    source_type: str | None = None
    source_id: str | None = None


class NotificationResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    message: str
    link: str | None = None
    category: str
    is_read: bool
    source_type: str | None = None
    source_id: str | None = None


class UnreadCount(BaseModel):
    count: int


class BulkNotifyRequest(BaseModel):
    """Internal endpoint: create notifications for all subscribers of a resource."""

    resource_type: str
    resource_id: str
    title: str
    message: str
    link: str | None = None
    category: str = "general"
    source_type: str | None = None
    source_id: str | None = None
