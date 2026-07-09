"""Subscription and Notification models — reusable notification system."""

from sqlalchemy import Boolean, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

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

    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(String(36), nullable=False, index=True)

    # Optional: notification preferences per subscription
    # e.g. {"email": true, "in_app": true}
    preferences = Column(JSONB, nullable=False, default=dict)


class Notification(Base, UUIDMixin, TimestampMixin):
    """In-app notification delivered to a user."""

    __tablename__ = "notifications"

    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    link = Column(String(512), nullable=True)
    category = Column(
        String(50),
        nullable=False,
        default="general",
        comment="tool_update | pipeline_status | dataset_update | system | general",
    )
    is_read = Column(Boolean, default=False, nullable=False, index=True)

    # Source reference — which resource triggered this notification
    source_type = Column(String(50), nullable=True)  # "tool", "pipeline", etc.
    source_id = Column(String(36), nullable=True)
