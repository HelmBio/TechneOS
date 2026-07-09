"""ComputeArtifact model — inventory of built & published artifacts.

Records every python wheel and docker image that has been built and published
for the platform: catalog tool/agent/app artifacts as well as platform-service
images and the tool-runtime base. Tool version definitions reference an artifact
by its coordinates (wheel package+version, or image repository+tag); this table
is the authoritative inventory those coordinates are validated against.

Named ``compute_artifacts`` to mirror ``compute_backends`` (the parallel "what
compute runs on" concept) and to avoid confusion with ``tool_run_artifacts``,
which stores per-run input/output files.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from core.models import Base, TimestampMixin, UUIDMixin


class ComputeArtifact(Base, UUIDMixin, TimestampMixin):
    """A built & published artifact (python wheel or docker image)."""

    __tablename__ = "compute_artifacts"

    kind: Column[str] = Column(
        Enum("wheel", "docker_image", name="artifact_kind"),
        nullable=False,
        index=True,
    )
    origin: Column[str] = Column(
        Enum(
            "catalog",
            "platform",
            "other",
            name="artifact_origin",
        ),
        nullable=False,
        default="other",
        index=True,
        comment="Provenance — 'catalog' (registered tool/agent/app) or 'platform' "
        "(service/runtime image the platform builds); lets the admin UI filter",
    )
    name = Column(
        String(512),
        nullable=False,
        comment="wheel package name OR image repository, e.g. 'techneos/dataset-profiler'",
    )
    version = Column(
        String(256),
        nullable=False,
        comment="wheel version OR image tag",
    )
    registry_url = Column(
        String(512),
        nullable=True,
        comment="PyPI index URL or ECR registry; null for local/dev",
    )
    digest = Column(
        String(256),
        nullable=True,
        comment="sha256 of the wheel file or image manifest digest",
    )
    size_bytes = Column(BigInteger, nullable=True)
    source_commit_sha = Column(String(64), nullable=True)
    source_repo = Column(String(255), nullable=True)
    status: Column[str] = Column(
        Enum("available", "deprecated", "deleted", name="artifact_status"),
        nullable=False,
        default="available",
        index=True,
    )
    metadata_ = Column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        comment="extra: python tags, arch/platform, discovered entry_points, ...",
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "kind", "name", "version", "registry_url", name="uq_artifact_identity"
        ),
    )
