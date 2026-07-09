"""ComputeBackend model — tracks available compute backends for tool execution."""

from sqlalchemy import Column, Enum, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from core.models import Base, TimestampMixin, UUIDMixin


class ComputeBackend(Base, UUIDMixin, TimestampMixin):
    """A registered compute backend (Docker, AWS Batch, Slurm, etc.).

    Backend *classes* live in packages/execution/backends/ — this table stores
    which backends are provisioned and available in a given deployment, along
    with their configuration and capabilities.
    """

    __tablename__ = "compute_backends"

    name = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    backend_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    status: Column[str] = Column(
        Enum("enabled", "disabled", "provisioning", name="compute_backend_status"),
        nullable=False,
        default="disabled",
    )
    config = Column(JSONB, nullable=False, default=dict)
    capabilities = Column(JSONB, nullable=False, default=dict)
