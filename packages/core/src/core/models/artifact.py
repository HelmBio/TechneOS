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

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models import Base, TimestampMixin, UUIDMixin


class ComputeArtifact(Base, UUIDMixin, TimestampMixin):
    """A built & published artifact (python wheel or docker image)."""

    __tablename__ = "compute_artifacts"

    kind: Mapped[str] = mapped_column(
        Enum("wheel", "docker_image", name="artifact_kind"),
        nullable=False,
        index=True,
    )
    origin: Mapped[str] = mapped_column(
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
    name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="wheel package name OR image repository, e.g. 'techneos/dataset-profiler'",
    )
    version: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="wheel version OR image tag",
    )
    registry_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="PyPI index URL or ECR registry; null for local/dev",
    )
    digest: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="sha256 of the wheel file or image manifest digest",
    )
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("available", "deprecated", "deleted", name="artifact_status"),
        nullable=False,
        default="available",
        index=True,
    )
    metadata_: Mapped[Any] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        comment="extra: python tags, arch/platform, discovered entry_points, ...",
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "kind", "name", "version", "registry_url", name="uq_artifact_identity"
        ),
    )
