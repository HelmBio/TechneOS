"""Platform-wide settings — instance-level key/value configuration."""

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import JSONB

from core.models import Base, TimestampMixin


class PlatformSetting(Base, TimestampMixin):
    """A single platform-wide setting, keyed by a stable string.

    Holds instance-level configuration that a ``platform_admin`` edits at
    runtime — distinct from per-org settings (``Org.settings``). The first
    consumer is the ``label_overrides`` key, whose ``value`` is a flat
    ``{label_key: display_string}`` map used to rename UI nav items and
    section headers per AIRE deployment.
    """

    __tablename__ = "platform_settings"

    key = Column(String(128), primary_key=True)
    value = Column(JSONB, nullable=False, default=dict)
