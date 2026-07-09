"""Pydantic schemas for tools and tool versions."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.models.common import TimestampSchema


def _validate_input_kind(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reject schemas whose top-level ``input_kind`` isn't in the registry.

    The runtime's :data:`techneos_tool_runtime.kinds.REGISTRY` is the single
    source of truth for what kinds exist. Catching an unsupported value
    here — at registration time — means the tool author gets immediate
    feedback (a 400 from ``build_and_register.py``) instead of a
    confusing runtime failure later.

    ``input_kind`` is optional, so an absent or ``None`` value passes
    through. An unrecognised string raises ``ValueError`` which Pydantic
    surfaces as a 422 / 400.
    """
    if not isinstance(schema, dict):
        return schema
    kind = schema.get("input_kind")
    if kind is None:
        return schema

    from techneos_tool_runtime import kinds

    if kinds.resolve(kind) is None:
        registered = sorted(k.value for k in kinds.REGISTRY)
        raise ValueError(
            f"Unknown input_kind {kind!r}. "
            f"Registered kinds: {registered}. "
            "If you need a new kind, add it to techneos_tool_runtime.kinds.REGISTRY "
            "or omit input_kind to fall back to the registry default."
        )
    return schema


# --- Tool ---


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    category: str = Field(
        default="general",
        pattern=r"^(docking|scoring|admet|ml|general|molecular-dynamics|quantum-chemistry|cheminformatics|bioinformatics|machine-learning|data-processing|other)$",
    )
    tool_type: str = Field(default="container", pattern=r"^(container|module|api|pypi|human)$")
    tags: list[str] = Field(default_factory=list)
    is_public: bool = False
    # Tool-level Markdown documentation. Was previously on each tool version;
    # moved here because it describes the tool, not a release.
    readme: str | None = Field(default=None, description="Tool documentation in Markdown")
    # Human tool config — only used when tool_type="human". When provided, the
    # first version is auto-created at tool registration time.
    assignment_type: str | None = Field(
        default=None, max_length=50, description="'user' for a specific user, 'team' for a team"
    )
    default_user_email: str | None = Field(
        default=None,
        max_length=255,
        description="Default user assignee email (mutually exclusive with default_team_slug)",
    )
    default_team_slug: str | None = Field(
        default=None,
        max_length=255,
        description="Default team assignee (mutually exclusive with default_user_email)",
    )
    # Legacy single-string field. Resolved against ``assignment_type`` at
    # write time → either default_user_email or default_team_slug.
    default_assignee: str | None = Field(
        default=None,
        max_length=255,
        description="(Deprecated) Default user email or team slug — use default_user_email / default_team_slug",
    )
    due_in_hours: int | None = Field(
        default=None, description="Default due time in hours from assignment creation"
    )
    require_attachments: bool | None = Field(
        default=None, description="Whether submission requires file attachments"
    )
    default_project_lead_email: str | None = Field(
        default=None,
        max_length=255,
        description="Optional project lead email (receives escalated task runs; resolved to UUID at run creation)",
    )
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(docking|scoring|admet|ml|general|molecular-dynamics|quantum-chemistry|cheminformatics|bioinformatics|machine-learning|data-processing|other)$",
    )
    tool_type: str | None = Field(default=None, pattern=r"^(container|module|api|pypi|human)$")
    tags: list[str] | None = None
    is_public: bool | None = None
    readme: str | None = None


class ToolResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    category: str
    tool_type: str
    tags: list[str]
    is_public: bool
    readme: str | None = None
    org_id: str
    created_by: str
    creator_name: str | None = None
    updated_by: str | None = None
    updated_by_name: str | None = None
    org_name: str | None = None
    version_count: int = 0
    latest_version: int | None = None
    latest_version_status: str | None = None


# --- Tool Version ---


class ToolVersionCreate(BaseModel):
    docker_image: str | None = Field(default=None, max_length=512)
    docker_tag: str | None = Field(default=None, max_length=128)
    package_name: str | None = Field(
        default=None,
        max_length=255,
        description="Python package name on the configured package index",
    )
    package_version: str | None = Field(
        default=None, max_length=64, description="Package version, e.g. 0.2.0"
    )
    entry_point: str | None = Field(
        default=None,
        max_length=255,
        description="Entry point function, e.g. module.submodule:function",
    )
    package_index_url: str | None = Field(
        default=None, max_length=512, description="Override platform package index URL"
    )
    agent_tools: list[str] | None = Field(
        default=None,
        description="List of async function names contributed to the Platform Assistant agent, e.g. ['calculate_molecule_properties']",
    )
    # Human tool configuration
    assignment_type: str | None = Field(
        default=None, max_length=50, description="'user' for a specific user, 'team' for a team"
    )
    default_user_email: str | None = Field(
        default=None, max_length=255, description="Default user assignee email"
    )
    default_team_slug: str | None = Field(
        default=None, max_length=255, description="Default team assignee"
    )
    default_assignee: str | None = Field(
        default=None,
        max_length=255,
        description="(Deprecated) Default user email or team slug — use default_user_email / default_team_slug",
    )
    due_in_hours: int | None = Field(
        default=None, description="Default due time in hours from assignment creation"
    )
    require_attachments: bool | None = Field(
        default=None, description="Whether submission requires file attachments"
    )
    priority: str | None = Field(
        default=None,
        max_length=20,
        description="Default task priority: low, medium, high, or urgent",
    )
    default_project_lead_email: str | None = Field(
        default=None,
        max_length=255,
        description="Optional project lead email (receives escalated task runs; resolved to UUID at run creation)",
    )
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    resource_requirements: dict[str, Any] = Field(default_factory=dict)
    changelog: str | None = Field(
        default=None, description="Per-release notes — what changed in this version"
    )

    _check_input_kind = field_validator("input_schema")(_validate_input_kind)


class ToolVersionUpdate(BaseModel):
    docker_image: str | None = None
    docker_tag: str | None = None
    package_name: str | None = None
    package_version: str | None = None
    entry_point: str | None = None
    package_index_url: str | None = None
    agent_tools: list[str] | None = None
    assignment_type: str | None = None
    default_user_email: str | None = None
    default_team_slug: str | None = None
    default_assignee: str | None = None
    due_in_hours: int | None = None
    require_attachments: bool | None = None
    priority: str | None = None
    default_project_lead_email: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    parameters_schema: dict[str, Any] | None = None
    resource_requirements: dict[str, Any] | None = None
    changelog: str | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|testing|active|deprecated)$")

    _check_input_kind = field_validator("input_schema")(_validate_input_kind)


class ToolVersionResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tool_id: str
    version: int
    docker_image: str | None = None
    docker_tag: str | None = None
    package_name: str | None = None
    package_version: str | None = None
    entry_point: str | None = None
    package_index_url: str | None = None
    agent_tools: list[str] | None = None
    assignment_type: str | None = None
    default_user_email: str | None = None
    default_team_slug: str | None = None
    default_assignee: str | None = None
    due_in_hours: int | None = None
    require_attachments: bool | None = None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    parameters_schema: dict[str, Any]
    resource_requirements: dict[str, Any]
    changelog: str | None = None
    priority: str | None = None
    default_project_lead_email: str | None = None
    status: str
    created_by: str
    creator_name: str | None = None
    updated_by: str | None = None
    updated_by_name: str | None = None
    # True when any run (tool/task/pipeline-step) references this version, in
    # which case its definition is frozen for traceability.
    has_runs: bool = False


class ToolVersionContentReplace(BaseModel):
    """Schema for replacing a tool version's functional content."""

    docker_image: str | None = Field(default=None, max_length=512)
    docker_tag: str | None = Field(default=None, max_length=128)
    package_name: str | None = Field(
        default=None,
        max_length=255,
        description="Python package name on the configured package index",
    )
    package_version: str | None = Field(
        default=None, max_length=64, description="Package version, e.g. 0.2.0"
    )
    entry_point: str | None = Field(
        default=None,
        max_length=255,
        description="Entry point function, e.g. module.submodule:function",
    )
    package_index_url: str | None = Field(
        default=None, max_length=512, description="Override platform package index URL"
    )
    agent_tools: list[str] | None = Field(
        default=None,
        description="List of async function names contributed to the Platform Assistant agent, e.g. ['calculate_molecule_properties']",
    )
    assignment_type: str | None = Field(
        default=None, max_length=50, description="'user' for a specific user, 'team' for a team"
    )
    default_user_email: str | None = Field(
        default=None, max_length=255, description="Default user assignee email"
    )
    default_team_slug: str | None = Field(
        default=None, max_length=255, description="Default team assignee"
    )
    default_assignee: str | None = Field(
        default=None,
        max_length=255,
        description="(Deprecated) Default user email or team slug — use default_user_email / default_team_slug",
    )
    due_in_hours: int | None = Field(
        default=None, description="Default due time in hours from assignment creation"
    )
    require_attachments: bool | None = Field(
        default=None, description="Whether submission requires file attachments"
    )
    priority: str | None = Field(
        default=None,
        max_length=20,
        description="Default task priority: low, medium, high, or urgent",
    )
    default_project_lead_email: str | None = Field(
        default=None,
        max_length=255,
        description="Optional project lead email (receives escalated task runs; resolved to UUID at run creation)",
    )
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    resource_requirements: dict[str, Any] = Field(default_factory=dict)
    changelog: str | None = Field(
        default=None, description="Per-release notes — what changed in this version"
    )

    _check_input_kind = field_validator("input_schema")(_validate_input_kind)


class RuntimeValidationRequest(BaseModel):
    """Runtime validation request — pypi-only since Phase 4 removed module."""

    package_name: str | None = Field(
        default=None, max_length=255, description="Python package name"
    )
    package_version: str | None = Field(default=None, max_length=64, description="Package version")
    entry_point: str | None = Field(
        default=None, max_length=255, description="Entry point function"
    )
    package_index_url: str | None = Field(
        default=None, max_length=512, description="Package index URL override"
    )
    test_script: str | None = Field(
        default=None, description="Test script that imports the entry point and asserts on outputs"
    )


class RuntimeValidationResponse(BaseModel):
    passed: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


class ToolWithVersions(ToolResponse):
    """Tool response including its version history."""

    versions: list[ToolVersionResponse] = Field(default_factory=list)


# Human task-run schemas moved to ``core.schemas.task_run`` (task-service).
