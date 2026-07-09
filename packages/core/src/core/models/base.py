"""Alias for models — re-export base and mixins."""

from core.models import Base, TimestampMixin, UUIDMixin

__all__ = ["Base", "TimestampMixin", "UUIDMixin"]
