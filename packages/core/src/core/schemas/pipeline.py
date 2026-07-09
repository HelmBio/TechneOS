"""Pydantic schemas for pipelines, runs, steps, and artifacts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema

# --- Pipeline Definition ---


class PipelineStepConfig(BaseModel):
    """Configuration for a single step in a pipeline definition.

    Known fields are validated explicitly; tool-type-specific fields
    (e.g. ``human_config``, ``package_name``, ``input_schema``) pass
    through via ``extra="allow"`` and are serialized verbatim into the
    stored JSONB.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=255)
    tool_slug: str = Field(min_length=1, max_length=255)
    tool_version: int | None = None  # None = latest
    tool_type: str | None = None  # resolved/overridden at dispatch time
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class PipelineEdge(BaseModel):
    """Edge in the pipeline DAG."""

    from_step: str
    to_step: str


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    readme: str | None = Field(default=None, description="Pipeline documentation in Markdown")
    category: str = "general"
    pipeline_type: str = Field(default="compute", pattern=r"^(compute|interactive|hybrid)$")
    steps: list[PipelineStepConfig] = Field(min_length=1)
    edges: list[PipelineEdge] = Field(default_factory=list)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    is_public: bool = False


class PipelineUpdate(BaseModel):
    """Update pipeline metadata, and (only while the pipeline has no runs) shape.

    The DAG shape (``steps``/``edges``/``parameters_schema``) is part of
    pipeline identity and is immutable once the pipeline has been run. The route
    accepts shape edits only for a still-unused pipeline; afterwards a structural
    change must be a fork. Tool pins and parameter values are tuned via versions.
    """

    name: str | None = None
    description: str | None = None
    readme: str | None = None
    category: str | None = None
    pipeline_type: str | None = Field(default=None, pattern=r"^(compute|interactive|hybrid)$")
    tags: list[str] | None = None
    is_public: bool | None = None

    # Shape edits — permitted only while the pipeline has zero runs (see route).
    steps: list[PipelineStepConfig] | None = None
    edges: list[PipelineEdge] | None = None
    parameters_schema: dict[str, Any] | None = None


class PipelineForkRequest(BaseModel):
    """Fork a pipeline to evolve its topology while keeping lineage."""

    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class PipelineResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    readme: str | None = None
    category: str = "general"
    pipeline_type: str = "compute"
    version: int = 0
    tags: list[str]
    is_public: bool

    # Canonical DAG shape — the pipeline's immutable identity.
    steps: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    topology_hash: str | None = None
    forked_from: str | None = None

    org_id: str
    created_by: str
    updated_by: str | None = None
    run_count: int = 0
    last_run_status: str | None = None
    version_count: int = 0
    latest_version: int | None = None
    latest_version_status: str | None = None

    # Denormalized display fields
    org_name: str | None = None
    created_by_email: str | None = None
    creator_name: str | None = None
    updated_by_name: str | None = None


# --- Pipeline Version ---


class PipelineVersionCreate(BaseModel):
    """Create a new version = a binding over the pipeline's fixed shape.

    Preferred form: ``bindings`` = ``{step_name -> {tool_version, parameters}}``.
    The full-DAG ``steps`` form is also accepted; the
    binding is derived from it and its shape must match the parent's.
    """

    bindings: dict[str, dict[str, Any]] | None = None
    steps: list[PipelineStepConfig] | None = None
    edges: list[PipelineEdge] | None = None
    parameters_schema: dict[str, Any] | None = None
    changelog: str | None = None


class PipelineVersionUpdate(BaseModel):
    bindings: dict[str, dict[str, Any]] | None = None
    changelog: str | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|testing|active|deprecated)$")


class PipelineVersionResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_id: str
    version: int
    # Per-version binding ({step_name -> {tool_version, parameters}}).
    bindings: dict[str, Any] = Field(default_factory=dict)
    # Effective DAG (parent shape merged with this version's bindings), computed
    # so the run dialog/graph can render.
    steps: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    status: str
    changelog: str | None = None
    created_by: str
    updated_by: str | None = None

    # Denormalized display fields
    creator_name: str | None = None
    updated_by_name: str | None = None

    # True when any pipeline run references this version, freezing its definition.
    has_runs: bool = False


class PipelineWithVersions(PipelineResponse):
    """Pipeline response including its version history."""

    versions: list[PipelineVersionResponse] = Field(default_factory=list)


class PipelineRunInputPaste(BaseModel):
    """Body for POST /pipeline-runs/inputs/paste — inline text content.

    The content is written to MinIO scratch space (no DB row created).
    ``parameter_name`` is the ``x-input`` property of the pipeline's
    parameters_schema that this file fills.
    """

    parameter_name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    content_type: str = Field(default="text/plain", max_length=100)
    file_name: str | None = Field(default=None, max_length=255)
    pipeline_slug: str = Field(min_length=1, max_length=255)
    pipeline_version: int


class PipelineRunInputStage(BaseModel):
    """Response from POST /pipeline-runs/inputs after staging (no DB row).

    Passed back at submit time so the service can relocate the file to the
    canonical per-run ``inputs/`` prefix and create the input artifact row.
    """

    id: str
    parameter_name: str
    file_name: str
    file_size: int
    content_type: str
    storage_bucket: str
    storage_key: str
    source: str = "upload"
    checksum_sha256: str = ""


class PipelineRunInputDownloadResponse(BaseModel):
    """Presigned URL for downloading a staged pipeline-run input file."""

    input_id: str
    download_url: str
    expires_in_seconds: int = 3600


class PipelineRunCreate(BaseModel):
    """Submit a new pipeline run.

    ``inputs`` references files staged in MinIO scratch space (uploaded via
    the /pipeline-runs/inputs endpoint). On submit the service relocates
    each file to the canonical per-run ``inputs/`` prefix and creates a
    PipelineRunArtifact row (``io_type='input'``).
    """

    pipeline_id: str
    version_id: str | None = (
        None  # If provided, run this specific version; otherwise use latest active
    )
    parameters: dict[str, Any] = Field(default_factory=dict)
    inputs: list[PipelineRunInputStage] = Field(default_factory=list)
    name: str | None = None


class PipelineRunResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_id: str
    name: str | None = None
    status: str
    parameters: dict[str, Any]
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    airflow_dag_id: str | None = None
    airflow_run_id: str | None = None
    org_id: str
    submitted_by: str
    restarted_from: str | None = None

    # Denormalized display fields
    pipeline_id: str | None = None
    pipeline_name: str | None = None
    pipeline_slug: str | None = None
    pipeline_version: int | None = None
    submitted_by_email: str | None = None
    org_name: str | None = None

    @classmethod
    def from_orm_with_names(cls, run: Any) -> "PipelineRunResponse":
        """Build response with denormalized names from eagerly loaded relationships."""
        data = cls.model_validate(run)
        if hasattr(run, "version") and run.version is not None:
            data.pipeline_version = run.version.version
            data.pipeline_id = run.version.pipeline_id
            if hasattr(run.version, "pipeline") and run.version.pipeline is not None:
                data.pipeline_name = run.version.pipeline.name
                data.pipeline_slug = run.version.pipeline.slug
        if hasattr(run, "submitter") and run.submitter is not None:
            data.submitted_by_email = run.submitter.email
        if hasattr(run, "org") and run.org is not None:
            data.org_name = run.org.name
        return data


class PipelineRunUpdate(BaseModel):
    """Update run status (used internally by orchestrator)."""

    status: str | None = Field(
        default=None,
        pattern=r"^(pending|queued|running|completed|failed|cancelled)$",
    )
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    airflow_dag_id: str | None = None
    airflow_run_id: str | None = None


# --- Pipeline Step Run ---


class StepRunResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    step_name: str
    tool_version_id: str | None = None
    status: str
    parameters: dict[str, Any]
    outputs: dict[str, Any]
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class StepStatusUpdate(BaseModel):
    """Update a step's status — used by Airflow task callbacks."""

    status: str = Field(pattern=r"^(pending|running|completed|failed|skipped|retrying)$")
    error_message: str | None = None
    outputs: dict[str, Any] | None = None


class PipelineRunDetail(PipelineRunResponse):
    """Run response with step details and artifacts."""

    steps: list[StepRunResponse] = Field(default_factory=list)
    artifacts: list["PipelineArtifactResponse"] = Field(default_factory=list)


# --- Run Artifact ---


class PipelineArtifactCreate(BaseModel):
    """Register a new artifact produced by a pipeline step."""

    io_type: str = "output"
    step_name: str | None = None
    name: str = Field(min_length=1, max_length=255)
    artifact_type: str = "file"
    file_name: str = Field(min_length=1, max_length=255)
    file_size: int
    content_type: str = "application/octet-stream"
    checksum_sha256: str | None = None
    storage_bucket: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)


class PipelineArtifactResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    io_type: str = "output"
    step_name: str | None = None
    name: str
    artifact_type: str
    file_name: str
    file_size: int
    content_type: str
    checksum_sha256: str | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None


class PipelineArtifactDownloadResponse(BaseModel):
    """Presigned URL for downloading an artifact."""

    artifact_id: str
    download_url: str
    expires_in_seconds: int = 3600


# Rebuild forward refs
PipelineRunDetail.model_rebuild()
