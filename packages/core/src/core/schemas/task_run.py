"""Pydantic schemas for task-service (human task runs)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Internal payloads (worker → task-service) ────────────────────────────


class TaskRunCreateInternal(BaseModel):
    """Internal payload — called by HumanBackend (worker)."""

    org_id: str
    tool_slug: str
    tool_version_id: str
    pipeline_run_id: str | None = None
    pipeline_step_run_id: str | None = None
    step_name: str | None = None
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    assigned_user_id: str | None = None
    assigned_user_email: str | None = Field(
        default=None, description="User email (resolved to user_id by server)"
    )
    assigned_team_slug: str | None = None
    project_lead_id: str | None = None
    project_lead_email: str | None = Field(
        default=None, description="Project lead email (resolved to UUID by server)"
    )
    due_at: str | None = Field(default=None, description="ISO-8601 deadline")
    created_by: str | None = None
    priority: str | None = None


# ── User-facing payloads ─────────────────────────────────────────────────


class TaskRunCreateFromTool(BaseModel):
    """User-facing — run a human-typed tool by slug."""

    tool_slug: str
    tool_version_id: str
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    input_ids: list[str] = Field(default_factory=list)
    assigned_user_id: str | None = None
    assigned_team_slug: str | None = None
    due_in_hours: int | None = None
    priority: str | None = None
    project_lead_email: str | None = Field(
        default=None, description="Project lead email (resolved to UUID by server)"
    )


class TaskRunSubmit(BaseModel):
    """Submit task fulfilment (assignee marks the run complete)."""

    output_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Output payload validated against the tool's output_schema",
    )
    message: str | None = Field(
        default=None,
        description="Completion message stored on the finish event (task_run_events.message)",
    )
    attachments: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "List of output file attachments, each with storage_path, file_name, "
            "content_type, file_size. New uploads should use POST /task-runs/{id}/outputs."
        ),
    )


class TaskRunDelegate(BaseModel):
    """Reassign a task run to another user."""

    to_user_id: str = Field(description="User ID to delegate to")
    new_due_at: str | None = Field(default=None, description="Optional new due date (ISO 8601)")
    reason: str | None = Field(default=None, description="Reason for delegation")


class TaskRunDecline(BaseModel):
    reason: str | None = Field(default=None, description="Why the assignee declined")


class TaskRunUpdate(BaseModel):
    """Post a follow-up 'update' action against a task run.

    Supports threaded conversations: optionally reply to a prior action via
    ``parent_event_id``, attaching a message and/or files.
    """

    message: str | None = Field(default=None, description="Free-text update message")
    parent_event_id: str | None = Field(
        default=None,
        description="Event id to thread this update under (a prior action)",
    )
    attachments: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Files to attach to this update, each with storage_path, file_name, "
            "content_type, file_size. New uploads should use POST "
            "/task-runs/{id}/outputs first."
        ),
    )


class TaskRunInputInfo(BaseModel):
    """Lightweight metadata for a bound input file."""

    id: str
    file_name: str
    file_size: int
    storage_key: str
    status: str


class TaskRunArtifactInfo(BaseModel):
    """Metadata for a single task-run artifact (any action_type)."""

    id: str
    action_type: str
    name: str
    file_name: str
    file_size: int
    content_type: str
    storage_key: str
    status: str
    event_id: str | None = None


# ── Response shapes ──────────────────────────────────────────────────────


class TaskRunResponse(BaseModel):
    """Detail view for a single task run."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    tool_id: str
    tool_slug: str
    tool_version_id: str
    tool_version_num: int | None = None

    pipeline_run_id: str | None = None
    pipeline_step_run_id: str | None = None
    step_name: str | None = None

    input_snapshot: dict[str, Any]

    status: str
    outcome: str | None = None
    # Single user-facing label that collapses (status, outcome, escalation)
    # into one of: pending | accepted | in progress | completed | declined |
    # cancelled | escalated | expired.
    display_status: str

    # Currently-active assignee snapshot (derived from current_assignment).
    assigned_user_id: str | None = None
    assigned_team_slug: str | None = None
    project_lead_id: str | None = None

    due_at: datetime | None = None
    original_due_at: datetime | None = None
    accepted_at: datetime | None = None

    snapshot_require_attachments: bool
    snapshot_due_in_hours: int | None = None
    snapshot_assignment_type: str
    priority: str = "medium"

    started_by: str
    started_at: datetime
    updated_at: datetime

    # --- Convenience denormalisations for the UI ---
    output_data: dict[str, Any] | None = None
    output_schema: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    finished_by: str | None = None
    finished_at: datetime | None = None
    assigned_user_name: str | None = None
    assigned_team_name: str | None = None
    started_by_name: str | None = None
    finished_by_name: str | None = None
    project_lead_name: str | None = None

    # --- Back-compat aliases for the existing frontend ---
    # The old shape exposed ``tool_run_id`` (the backing ToolRun, which we
    # no longer create), ``escalated_at``, ``delegation_history``, and
    # ``require_attachments``. They're surfaced here so the web client
    # continues to render task runs without changes.
    tool_run_id: str | None = None
    escalated_at: datetime | None = None
    delegation_history: list[dict[str, Any]] = Field(default_factory=list)
    require_attachments: bool | None = None

    # Full status / event history — every state transition from the
    # task_run_events log. Replaces the narrower delegation_history
    # view in the UI's status timeline.
    event_history: list[dict[str, Any]] = Field(default_factory=list)

    # Bound input files — hydrated from task_run_artifacts (action='start').
    inputs: list[TaskRunInputInfo] = Field(default_factory=list)

    # Full artifact set across all actions (start / update / finish).
    artifacts: list[TaskRunArtifactInfo] = Field(default_factory=list)


class TaskRunListItem(BaseModel):
    """Row in a task run list response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    tool_id: str
    tool_slug: str
    tool_version_id: str
    tool_version_num: int | None = None
    status: str
    outcome: str | None = None
    display_status: str

    assigned_user_id: str | None = None
    assigned_user_name: str | None = None
    assigned_team_slug: str | None = None
    assigned_team_name: str | None = None
    project_lead_id: str | None = None

    due_at: datetime | None = None
    accepted_at: datetime | None = None
    priority: str = "medium"

    pipeline_run_id: str | None = None
    step_name: str | None = None

    started_by: str
    started_by_name: str | None = None
    started_at: datetime
    updated_at: datetime

    # Back-compat fields the web client reads off list rows.
    tool_run_id: str | None = None
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    finished_by: str | None = None
    finished_by_name: str | None = None
    finished_at: datetime | None = None
    output_data: dict[str, Any] | None = None
    delegation_history: list[dict[str, Any]] = Field(default_factory=list)


# ── File upload responses ────────────────────────────────────────────────


class TaskInputUploadResponse(BaseModel):
    """Response for staging an input file."""

    input_id: str
    storage_path: str
    compounds_count: int | None = None
    file_size: int


class TaskOutputUploadResponse(BaseModel):
    """Response for uploading an output file."""

    output_id: str
    storage_path: str
    file_name: str
    content_type: str
    file_size: int


class TaskFileDownloadResponse(BaseModel):
    """Response for requesting a presigned download URL."""

    download_url: str
    storage_path: str
