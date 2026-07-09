"""Pydantic schemas for tool runs and artifacts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema

# ── Input reference (staged in scratch space, no DB row) ────────────


class ToolRunInputRef(BaseModel):
    """Reference to a staged input file in MinIO scratch space.

    Returned by the upload/paste endpoints and passed back at submit time
    so the service can relocate the file to the canonical per-run prefix
    and create the ToolRunArtifact row.
    """

    id: str
    parameter_name: str
    file_name: str
    file_size: int = 0
    content_type: str
    source: str = "upload"
    storage_key: str
    checksum_sha256: str = ""


# ── Tool Run ─────────────────────────────────────────────────────────


class ToolRunCreate(BaseModel):
    """Submit a new tool run.

    ``inputs`` references files staged in MinIO scratch space (uploaded
    via the /tool-runs/inputs endpoint). On submit the service relocates
    each file to the canonical per-run prefix and creates a
    ToolRunArtifact row (``io_type='input'``).
    """

    tool_id: str
    version_id: str | None = None  # if None, latest active version is used
    parameters: dict[str, Any] = Field(default_factory=dict)
    inputs: list[ToolRunInputRef] = Field(default_factory=list)


class ToolRunUpdate(BaseModel):
    """Update run status — typically called by the orchestrator callback."""

    status: str | None = Field(
        default=None,
        pattern=r"^(pending|queued|running|completed|failed|cancelled)$",
    )
    error_message: str | None = None
    outputs: dict[str, Any] | None = None
    log_storage_key: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    airflow_dag_id: str | None = None
    airflow_run_id: str | None = None


class ToolRunResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tool_version_id: str
    status: str
    parameters: dict[str, Any]
    outputs: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    log_storage_key: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    airflow_dag_id: str | None = None
    airflow_run_id: str | None = None
    org_id: str
    submitted_by: str
    restarted_from: str | None = None

    # Denormalized display fields
    tool_id: str | None = None
    tool_slug: str | None = None
    tool_name: str | None = None
    tool_version_num: int | None = None
    submitted_by_email: str | None = None
    org_name: str | None = None

    @classmethod
    def from_orm_with_names(cls, run: Any) -> "ToolRunResponse":
        """Build response with denormalized names from eagerly loaded relationships."""
        data = cls.model_validate(
            {
                "id": run.id,
                "tool_version_id": run.tool_version_id,
                "status": run.status,
                "parameters": run.parameters,
                "outputs": run.outputs,
                "error_message": run.error_message,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "airflow_dag_id": run.airflow_dag_id,
                "airflow_run_id": run.airflow_run_id,
                "log_storage_key": run.log_storage_key,
                "org_id": run.org_id,
                "submitted_by": run.submitted_by,
                "restarted_from": run.restarted_from,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            }
        )
        tv = getattr(run, "tool_version", None)
        if tv is not None:
            data.tool_version_num = tv.version
            data.tool_id = tv.tool_id
            tool = getattr(tv, "tool", None)
            if tool is not None:
                data.tool_slug = tool.slug
                data.tool_name = tool.name
        submitter = getattr(run, "submitter", None)
        if submitter is not None:
            data.submitted_by_email = submitter.email
        org = getattr(run, "org", None)
        if org is not None:
            data.org_name = org.name
        return data


# ── Input staging (scratch-only, no DB row) ─────────────────────────


class ToolRunInputPaste(BaseModel):
    """Body for POST /tool-runs/inputs/paste — inline text content.

    The content is written to MinIO scratch space (no DB row created).
    ``content_type`` controls the parser the runtime uses later.
    """

    parameter_name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    content_type: str = Field(default="text/plain", max_length=100)
    file_name: str | None = Field(default=None, max_length=255)
    tool_slug: str = Field(min_length=1, max_length=255)
    tool_version: int


class ToolRunInputStage(BaseModel):
    """Response from POST /tool-runs/inputs after staging (no DB row)."""

    id: str
    parameter_name: str
    file_name: str
    file_size: int
    content_type: str
    storage_bucket: str
    storage_key: str
    source: str = "upload"
    checksum_sha256: str = ""


class ToolRunInputDownloadResponse(BaseModel):
    """Presigned URL for downloading a tool-run input file."""

    input_id: str
    download_url: str
    expires_in_seconds: int = 3600


# ── Tool Run Artifact (unified input + output) ──────────────────────


class ToolRunArtifactCreate(BaseModel):
    """Register a new output artifact for a tool run.

    Called by the worker after uploading a file to MinIO at the canonical
    per-run prefix.
    """

    file_name: str = Field(min_length=1, max_length=255)
    file_size: int
    content_type: str = "application/octet-stream"
    checksum_sha256: str | None = None
    storage_bucket: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolRunArtifactResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tool_run_id: str
    io_type: str
    file_name: str
    file_size: int
    content_type: str
    checksum_sha256: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")


class ToolRunArtifactDownloadResponse(BaseModel):
    """Presigned URL for downloading an artifact."""

    artifact_id: str
    download_url: str
    expires_in_seconds: int = 3600


# ── Detail (run + artifacts) ────────────────────────────────────────


class ToolRunDetail(ToolRunResponse):
    """Run response with all artifacts (inputs + outputs)."""

    artifacts: list[ToolRunArtifactResponse] = Field(default_factory=list)


ToolRunDetail.model_rebuild()
