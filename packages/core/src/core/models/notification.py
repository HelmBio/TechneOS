"""Subscription and Notification models — reusable notification system."""

from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models import Base, TimestampMixin, UUIDMixin


class Subscription(Base, UUIDMixin, TimestampMixin):
    """User subscription to a resource for receiving notifications.

    resource_type examples: "tool", "pipeline", "dataset"
    resource_id: the UUID of the followed resource
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "resource_type", "resource_id", name="uq_subscription"),
    )

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # Optional: notification preferences per subscription
    # e.g. {"email": true, "in_app": true}
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Notification(Base, UUIDMixin, TimestampMixin):
    """In-app notification delivered to a user."""

    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="general",
        comment="tool_update | pipeline_status | dataset_update | system | general",
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Source reference — which resource triggered this notification
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "tool", "pipeline", etc.
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
