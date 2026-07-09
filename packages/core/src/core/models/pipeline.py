"""Pipeline definition and execution models."""

from typing import Any, cast

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.tool import ToolVersion  # noqa: F401  — register for FK resolution
from core.models.user import Org, User  # noqa: F401  — register for relationship resolution


class Pipeline(Base, UUIDMixin, TimestampMixin):
    """A reusable pipeline definition — metadata, ownership, and canonical shape.

    The pipeline owns the **shape** (the canonical, immutable DAG):
    per-step ``name``/``tool_slug``/``depends_on``/``inputs`` wiring in ``steps``,
    the ``edges``, and the run-I/O ``parameters_schema``. ``topology_hash`` is the
    structural fingerprint of that shape (its identity beyond the slug). Each
    :class:`PipelineVersion` is a *binding* over this shape — it pins tool
    versions and parameter values but never changes the shape. Structural
    evolution is a fork (``forked_from``), not a new version.
    """

    __tablename__ = "pipelines"

    name = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(
        String(50),
        nullable=False,
        default="general",
        comment="docking | scoring | admet | ml | general | molecular-dynamics | quantum-chemistry | cheminformatics | bioinformatics | machine-learning | data-processing | other",
    )
    pipeline_type: Column[str] = Column(
        Enum("compute", "interactive", "hybrid", name="pipeline_type"),
        nullable=False,
        default="compute",
        comment="compute | interactive | hybrid",
    )
    readme = Column(Text, nullable=True, comment="Pipeline documentation in Markdown")

    tags = Column(JSONB, nullable=False, default=list)
    is_public = Column(Boolean, default=False, nullable=False)

    # Canonical DAG shape. The shape is immutable once the pipeline
    # has runs; structural change requires a fork. Steps here are shape-only:
    # {name, tool_slug, depends_on, inputs} — no tool_version / parameters (those
    # are per-version bindings). parameters_schema is the run-I/O contract, with
    # run-input defaults carried as JSON-Schema `default` on each property.
    steps = Column(JSONB, nullable=False, default=list)
    edges = Column(JSONB, nullable=False, default=list)
    parameters_schema = Column(JSONB, nullable=False, default=dict)
    # SHA-256 of the canonical topology — the pipeline's structural identity.
    # Computed by core.pipeline_topology.topology_hash.
    topology_hash = Column(String(64), nullable=True, index=True)

    # Lineage: set when this pipeline was created by forking another to evolve
    # its topology while keeping continuity.
    forked_from = Column(String(36), ForeignKey("pipelines.id"), nullable=True)

    # Ownership
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Relationships
    versions = relationship(
        "PipelineVersion", back_populates="pipeline", cascade="all, delete-orphan"
    )
    parent = relationship(
        "Pipeline", remote_side="Pipeline.id", foreign_keys=[forked_from], uselist=False
    )
    org = relationship("Org", foreign_keys=[org_id], lazy="joined")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = relationship("User", foreign_keys=[updated_by], lazy="joined")

    @property
    def runs(self) -> list[Any]:
        """All runs across all versions."""
        result: list[Any] = []
        for v in self.versions or []:
            result.extend(v.runs or [])
        return result

    @property
    def version(self) -> int:
        """Current (latest) version number."""
        if not self.versions:
            return 0
        return cast(int, max(v.version for v in self.versions))

    @property
    def run_count(self) -> int:
        """Number of runs for this pipeline."""
        return len(self.runs)

    @property
    def last_run_status(self) -> str | None:
        """Status of the most recent run, or None if no runs exist."""
        all_runs = self.runs
        if not all_runs:
            return None
        latest = max(all_runs, key=lambda r: r.created_at)
        return cast(str | None, latest.status)

    @property
    def version_count(self) -> int:
        """Number of versions for this pipeline."""
        return len(self.versions) if self.versions else 0

    @property
    def latest_version(self) -> int | None:
        """Highest version number, or None if no versions exist."""
        if not self.versions:
            return None
        return cast(int | None, max(v.version for v in self.versions))

    @property
    def latest_version_status(self) -> str | None:
        """Status of the highest version, or None if no versions exist."""
        if not self.versions:
            return None
        latest = max(self.versions, key=lambda v: v.version)
        return cast(str | None, latest.status)

    @property
    def org_name(self) -> str | None:
        """Organization name from the related Org."""
        return self.org.name if self.org else None

    @property
    def created_by_email(self) -> str | None:
        """Creator email from the related User."""
        return self.creator.email if self.creator else None

    @property
    def creator_name(self) -> str | None:
        """Resolved creator full name for API responses."""
        return self.creator.full_name if self.creator else None

    @property
    def updated_by_name(self) -> str | None:
        """Resolved updater full name for API responses."""
        return self.updater.full_name if self.updater else None


class PipelineVersion(Base, UUIDMixin, TimestampMixin):
    """A *binding* over a pipeline's fixed shape.

    A version does not redraw the DAG — it pins which tool version runs at each
    step and the parameter values used, via ``bindings``:
    ``{ step_name -> { tool_version, parameters } }``. The orchestrator merges
    ``Pipeline.steps`` (shape) with these bindings at dispatch. Status lifecycle:
    draft -> testing -> active -> deprecated.
    """

    __tablename__ = "pipeline_versions"

    pipeline_id = Column(
        String(36),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = Column(Integer, nullable=False)

    # Per-version binding over the parent's shape:
    # { step_name -> { tool_version: int|null, parameters: {...} } }
    bindings = Column(JSONB, nullable=False, default=dict)

    # Status lifecycle
    status: Column[str] = Column(
        Enum(
            "draft",
            "testing",
            "active",
            "deprecated",
            name="pipeline_version_status",
        ),
        nullable=False,
        default="draft",
    )

    # Release info
    changelog = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Relationships
    runs = relationship("PipelineRun", back_populates="version", cascade="all, delete-orphan")
    pipeline = relationship("Pipeline", back_populates="versions")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = relationship("User", foreign_keys=[updated_by], lazy="joined")

    @property
    def creator_name(self) -> str | None:
        """Resolved creator full name for API responses."""
        return self.creator.full_name if self.creator else None

    @property
    def updated_by_name(self) -> str | None:
        """Resolved updater full name for API responses."""
        return self.updater.full_name if self.updater else None

    @property
    def effective_steps(self) -> list[dict[str, Any]]:
        """Reconstruct the executable step list from parent shape + bindings.

        This is the single source consumed by the orchestrator and the API
        response: ``Pipeline.steps`` (shape) merged with this version's
        ``bindings`` (per-step ``tool_version`` + ``parameters``).
        """
        from core.pipeline_topology import merge

        shape_steps = self.pipeline.steps if self.pipeline else []
        return merge(shape_steps, cast("dict[str, dict[str, Any]]", self.bindings or {}))


class PipelineRun(Base, UUIDMixin, TimestampMixin):
    """A single execution of a pipeline version.

    Tracks overall status, timing, and the parameters used for the run.
    Individual step statuses are tracked via PipelineStepRun.
    """

    __tablename__ = "pipeline_runs"

    name = Column(String(255), nullable=True)

    version_id = Column(
        String(36),
        ForeignKey("pipeline_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Runtime
    status: Column[str] = Column(
        Enum(
            "pending",
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            name="pipeline_run_status",
        ),
        nullable=False,
        default="pending",
    )
    parameters = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # External orchestrator reference
    airflow_dag_id = Column(String(255), nullable=True)
    airflow_run_id = Column(String(255), nullable=True)

    # Who launched it
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Restart lineage (nullable — only set when this run was created via restart)
    restarted_from = Column(String(36), ForeignKey("pipeline_runs.id"), nullable=True)

    # Relationships
    version = relationship("PipelineVersion", back_populates="runs")
    submitter = relationship("User", foreign_keys=[submitted_by])
    org = relationship("Org", foreign_keys=[org_id])
    steps = relationship("PipelineStepRun", back_populates="run", cascade="all, delete-orphan")
    artifacts = relationship(
        "PipelineRunArtifact", back_populates="run", cascade="all, delete-orphan"
    )


class PipelineStepRun(Base, UUIDMixin, TimestampMixin):
    """Status tracker for a single step within a pipeline run."""

    __tablename__ = "pipeline_step_runs"

    run_id = Column(
        String(36),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_name = Column(String(255), nullable=False)
    tool_version_id = Column(String(36), ForeignKey("tool_versions.id"), nullable=True)

    status: Column[str] = Column(
        Enum(
            "pending",
            "running",
            "completed",
            "failed",
            "skipped",
            "retrying",
            "cancelled",
            name="step_run_status",
        ),
        nullable=False,
        default="pending",
    )
    parameters = Column(JSONB, nullable=False, default=dict)
    outputs = Column(JSONB, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    run = relationship("PipelineRun", back_populates="steps")


class PipelineRunArtifact(Base, UUIDMixin, TimestampMixin):
    """A file attached to a pipeline run — an input or a step output.

    ``io_type`` distinguishes inputs (staged before the run, bound on
    submit) from outputs (produced by a step). Inputs live under the run's
    ``inputs/`` prefix and carry their owning ``step_name`` (the step the
    ``x-input`` parameter feeds, or null for pipeline-level inputs);
    outputs live under their producing step's prefix. This mirrors
    ``tool_run_artifacts``. Artifacts are stored in object storage; this
    table indexes their metadata for search and retrieval.
    """

    __tablename__ = "pipeline_run_artifacts"

    run_id = Column(
        String(36),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    io_type = Column(
        String(20),
        nullable=False,
        default="output",
        comment="'input' or 'output'",
    )
    step_name = Column(String(255), nullable=True, comment="null if pipeline-level artifact")
    name = Column(String(255), nullable=False)
    artifact_type = Column(
        String(50),
        nullable=False,
        default="file",
        comment="file | table | plot | model | report",
    )

    # Object store reference
    storage_bucket = Column(String(255), nullable=False)
    storage_key = Column(String(1024), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    content_type = Column(String(100), nullable=False, default="application/octet-stream")
    checksum_sha256 = Column(String(64), nullable=True)

    # Structured metadata for indexing/search
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

    # Relationships
    run = relationship("PipelineRun", back_populates="artifacts")
