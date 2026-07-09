"""ToolRun and ToolRunArtifact models.

A ToolRun is a standalone execution of a single ToolVersion. Structurally
the same as a 1-step PipelineRun: the orchestrator builds a single-element
steps array and dispatches the existing techneos_airflow_pipeline DAG.

Inputs come from three sources, all materialised through MinIO:
    1. Platform datasets (referenced by slug:vN or UUID in `parameters`).
    2. Uploaded files (written to scratch space at upload time, then bound).
    3. Pasted text content (synthesised into a file written to scratch space).

On submit the scratch files are relocated to a canonical per-run prefix
and a ToolRunArtifact row (``io_type='input'``) is created. The corresponding
entry in ``ToolRun.parameters`` becomes a typed pointer::

    {"type": "paste"|"upload", "input_id": ...}

for uploaded/pasted inputs, or ``{"type": "dataset", "ref": "slug:vN"}``
for platform datasets.
"""

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.tool import ToolVersion  # noqa: F401  — register for FK resolution
from core.models.user import Org, User  # noqa: F401  — register for relationship resolution


class ToolRun(Base, UUIDMixin, TimestampMixin):
    """A single execution of a ToolVersion."""

    __tablename__ = "tool_runs"

    tool_version_id = Column(
        String(36),
        ForeignKey("tool_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Column[str] = Column(
        Enum(
            "pending",
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            name="tool_run_status",
        ),
        nullable=False,
        default="pending",
    )
    parameters = Column(JSONB, nullable=False, default=dict)
    outputs = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # External orchestrator reference
    airflow_dag_id = Column(String(255), nullable=True)
    airflow_run_id = Column(String(255), nullable=True)

    # Persisted logs — set when the run reaches a terminal state
    log_storage_key = Column(String(1024), nullable=True)

    # Ownership
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Restart lineage — set when this run was created via /restart
    restarted_from = Column(String(36), ForeignKey("tool_runs.id"), nullable=True)

    # Relationships
    tool_version = relationship(
        "ToolVersion", foreign_keys=[tool_version_id], back_populates="runs", lazy="joined"
    )
    submitter = relationship("User", foreign_keys=[submitted_by])
    org = relationship("Org", foreign_keys=[org_id])
    artifacts = relationship("ToolRunArtifact", back_populates="run", cascade="all, delete-orphan")


class ToolRunArtifact(Base, UUIDMixin, TimestampMixin):
    """Every file attached to a ToolRun, in one table.

    ``io_type`` distinguishes inputs (staged before the run, bound on
    submit) from outputs (produced by the worker). Input-specific metadata
    (``parameter_name``, ``source``) and output-specific metadata
    (``artifact_type``) are stored in the ``metadata`` JSONB column.

    Artifact rows are created *after* the file lands at its canonical
    per-run MinIO key — there is no separate staging DB row.
    """

    __tablename__ = "tool_run_artifacts"

    tool_run_id = Column(
        String(36),
        ForeignKey("tool_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    io_type = Column(
        String(20),
        nullable=False,
        comment="'input' or 'output'",
    )

    file_name = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    content_type = Column(String(100), nullable=False, default="application/octet-stream")
    checksum_sha256 = Column(String(64), nullable=True)

    storage_bucket = Column(String(255), nullable=False)
    storage_key = Column(String(1024), nullable=False)

    # Lifecycle: 'active' for all rows (no longer separate staged/bound)
    status = Column(String(20), nullable=False, default="active")

    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

    run = relationship("ToolRun", back_populates="artifacts")
