"""ComputeBackend model — tracks available compute backends for tool execution."""

from typing import Any

from sqlalchemy import Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models import Base, TimestampMixin, UUIDMixin


class ComputeBackend(Base, UUIDMixin, TimestampMixin):
    """A registered compute backend (Docker, AWS Batch, Slurm, etc.).

    Backend *classes* live in the execution layer — this table stores
    which backends are provisioned and available in a given deployment, along
    with their configuration and capabilities.
    """

    __tablename__ = "compute_backends"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    backend_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("enabled", "disabled", "provisioning", name="compute_backend_status"),
        nullable=False,
        default="disabled",
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
