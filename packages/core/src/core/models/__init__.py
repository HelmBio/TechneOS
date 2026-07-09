"""SQLAlchemy base model and common mixins."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class UUIDMixin:
    """Mixin that adds a UUID primary key."""

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
