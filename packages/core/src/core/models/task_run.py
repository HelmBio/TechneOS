"""Task-service models — runtime side of human tasks.

These models own the full lifecycle of a human task execution. The tool
definition (``Tool`` / ``ToolVersion`` / ``HumanConfig``) lives in
tool-service; task-service references it via ``tool_version_id`` /
``tool_id`` (soft FKs, enforced at the DB layer since both schemas live
in the same Postgres instance).

Layout — one state row, one action log, one artifact table:

    TaskRun            overall state of the assignment (current holder +
                       final submission denormalised onto the row)
    TaskRunEvent       append-only log of *actions*; threads via
                       ``parent_event_id``; ``action_type`` is drawn from
                       the platform ``task_action_types`` list
    TaskRunArtifact    every file for the run, tagged with the ``action_type``
                       that produced/consumed it (merges the old
                       task_run_inputs + task_run_outputs)

The old ``TaskRunAssignment`` chain is gone: the current holder lives in
denormalised columns on ``TaskRun`` and the delegation/escalation history
is reconstructed from ``start`` / ``delegate`` / ``escalate`` events.
Notification delivery dedupe now belongs to notification-service.
"""
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.tool import Tool, ToolVersion  # noqa: F401  — register FK resolution
from core.models.user import Org, User  # noqa: F401  — register FK resolution

# ── Status / outcome / actor enums ──────────────────────────────────────
#
# These three stay as Postgres enums (small, stable, lifecycle-critical).
# The action vocabulary is intentionally *not* an enum — it's a
# runtime-editable controlled list in platform_settings (see
# ``core.task_actions``), stored here as a plain String column.


_TASK_RUN_STATUS = Enum(
    "pending",
    "accepted",
    "in_progress",
    "terminal",
    name="task_run_status",
    create_type=False,
)

_TASK_RUN_OUTCOME = Enum(
    "completed",
    "declined",
    "cancelled",
    "expired",
    name="task_run_outcome",
    create_type=False,
)

_TASK_RUN_ACTOR_TYPE = Enum(
    "user",
    "system",
    "pipeline",
    name="task_run_actor_type",
    create_type=False,
)


# ── TaskRun ─────────────────────────────────────────────────────────────


class TaskRun(Base, UUIDMixin):
    """The overall state of one human-task assignment.

    Holds the live state (status / current holder) plus the final
    submission. Everything that grows over time — the action log and the
    files — lives in the satellite tables (``TaskRunEvent`` /
    ``TaskRunArtifact``).

    Timestamp / actor columns mirror the action vocabulary: ``started_by`` /
    ``started_at`` for the ``start`` action (there is no separate created_*),
    ``finished_by`` / ``finished_at`` for the ``finish`` action.
    """

    __tablename__ = "task_runs"

    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False)

    # Denormalised tool info — set at creation so task-service can render
    # list views without crossing into tool-service.
    tool_id = Column(String(36), ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False)
    tool_slug = Column(String(255), nullable=False)
    tool_version_id = Column(
        String(36), ForeignKey("tool_versions.id", ondelete="RESTRICT"), nullable=False
    )
    # Denormalised numeric tool version (the N in "v{N}") so list/detail views
    # don't need to join tool_versions.
    tool_version_no = Column(Integer, nullable=True)

    # Pipeline linkage (replaces the old tool_run_id linkage)
    pipeline_run_id = Column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
    pipeline_step_run_id = Column(
        String(36), ForeignKey("pipeline_step_runs.id", ondelete="SET NULL"), nullable=True
    )
    step_name = Column(String(255), nullable=True)

    # Frozen structured input parameters captured at creation (was
    # ``input_snapshot`` — renamed to drop the overloaded "snapshot" word;
    # input *files* now live in TaskRunArtifact with action_type='start').
    input_params = Column(JSONB, nullable=False, default=dict)

    # Backwards-compat alias: some code paths (and tests) still reference
    # `input_snapshot` as the attribute name. Provide a read-only alias to
    # maintain compatibility while the underlying storage uses `input_params`.
    @property
    def input_snapshot(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self.input_params or {})

    # Lifecycle: status is the active vs terminal flag; outcome is the
    # terminal disposition, set only when status='terminal' (CHECK enforced
    # at the DB level).
    status: Column[str] = Column(_TASK_RUN_STATUS, nullable=False, default="pending")
    outcome: Column[str] = Column(_TASK_RUN_OUTCOME, nullable=True)

    # Current holder — denormalised onto the row (replaces the
    # task_run_assignments chain + current_assignment_id pointer). The
    # full holder history is reconstructed from start/delegate/escalate
    # events.
    assigned_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    assigned_team_slug = Column(String(255), nullable=True)
    project_lead_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    due_at = Column(DateTime(timezone=True), nullable=True)
    original_due_at = Column(DateTime(timezone=True), nullable=True)

    # Frozen copy of the tool's HumanConfig captured at creation (was the
    # ``snapshot_*`` columns).
    require_attachments = Column(Boolean, nullable=False, default=False)
    cfg_due_in_hours = Column(Integer, nullable=True)
    assignment_type = Column(String(50), nullable=False)
    priority = Column(String(20), nullable=False, default="medium")

    # 'start' action — who created/started the run and when (replaces the
    # generic created_by / created_at).
    started_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    # Final submission — captured by the 'finish' action and denormalised
    # here for cheap list/detail rendering. ``output_data`` is the
    # structured payload validated against the tool's output_schema.
    # Output *files* live in TaskRunArtifact (action_type='finish').
    output_data = Column(JSONB, nullable=False, default=dict)
    finished_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(status = 'terminal' AND outcome IS NOT NULL) "
            "OR (status <> 'terminal' AND outcome IS NULL)",
            name="ck_task_runs_outcome_iff_terminal",
        ),
    )

    # Relationships
    tool = relationship("Tool", foreign_keys=[tool_id])
    tool_version = relationship("ToolVersion", foreign_keys=[tool_version_id])
    starter = relationship("User", foreign_keys=[started_by])
    finisher = relationship("User", foreign_keys=[finished_by])
    assigned_user = relationship("User", foreign_keys=[assigned_user_id])
    project_lead = relationship("User", foreign_keys=[project_lead_id])
    events = relationship(
        "TaskRunEvent",
        back_populates="task_run",
        cascade="all, delete-orphan",
        foreign_keys="TaskRunEvent.task_run_id",
    )
    artifacts = relationship(
        "TaskRunArtifact",
        back_populates="task_run",
        cascade="all, delete-orphan",
        foreign_keys="TaskRunArtifact.task_run_id",
    )


# ── TaskRunEvent ────────────────────────────────────────────────────────


class TaskRunEvent(Base, UUIDMixin):
    """Append-only log of *actions* taken on a TaskRun.

    ``action_type`` is a slug from the platform ``task_action_types`` list
    (validated at the application layer, not a DB enum, so it stays
    runtime-editable). ``parent_event_id`` threads a follow-up action onto
    an earlier one (e.g. an 'update' message + files in reply to a prior
    action), enabling threaded conversations on the run timeline.
    """

    __tablename__ = "task_run_events"

    task_run_id = Column(String(36), ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(50), nullable=False)
    parent_event_id = Column(
        String(36), ForeignKey("task_run_events.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actor_type: Column[str] = Column(_TASK_RUN_ACTOR_TYPE, nullable=False)
    message = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    occurred_at = Column(DateTime(timezone=True), nullable=False)

    task_run = relationship("TaskRun", back_populates="events", foreign_keys=[task_run_id])
    actor = relationship("User", foreign_keys=[actor_user_id])
    parent = relationship(
        "TaskRunEvent", remote_side="TaskRunEvent.id", foreign_keys=[parent_event_id]
    )
    artifacts = relationship(
        "TaskRunArtifact",
        back_populates="event",
        foreign_keys="TaskRunArtifact.event_id",
    )


# ── TaskRunArtifact ─────────────────────────────────────────────────────


class TaskRunArtifact(Base, UUIDMixin, TimestampMixin):
    """Every file attached to a TaskRun, in one table.

    Merges the old ``TaskRunInput`` + ``TaskRunOutput``. The ``action_type``
    records which action the file belongs to — inputs are ``start``,
    submitted outputs are ``finish``, conversational attachments are
    ``update`` — and is also the MinIO key segment:
    ``task-runs/{tool_slug}/v{N}/{task_run_id}/{action_type}/{id}/{file_name}``.

    ``task_run_id`` is nullable so ``start`` inputs can be staged before the
    run exists (``status='staged'``), then bound on creation
    (``status='bound'``). ``event_id`` links a file to the exact action that
    carried it (including threaded ``update`` actions).
    """

    __tablename__ = "task_run_artifacts"

    task_run_id = Column(String(36), ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=True)
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False)
    action_type = Column(String(50), nullable=False)
    event_id = Column(
        String(36), ForeignKey("task_run_events.id", ondelete="SET NULL"), nullable=True
    )

    name = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    content_type = Column(String(100), nullable=False, default="application/octet-stream")
    checksum_sha256 = Column(String(64), nullable=True)

    storage_bucket = Column(String(255), nullable=False)
    storage_key = Column(String(1024), nullable=False)

    # staged → bound (for start inputs); active (for outputs/updates).
    status = Column(String(20), nullable=False, default="active")

    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

    task_run = relationship("TaskRun", back_populates="artifacts", foreign_keys=[task_run_id])
    event = relationship("TaskRunEvent", back_populates="artifacts", foreign_keys=[event_id])
