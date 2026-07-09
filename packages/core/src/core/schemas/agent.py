"""Pydantic schemas for agent definitions, agentic runs, and tasks."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema

# --- Agent Definition ---


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    agent_type: str = Field(
        default="conversational",
        pattern=r"^(conversational|autonomous|reactive|research)$",
    )
    framework: str = Field(
        default="custom",
        pattern=r"^(custom|langchain|autogen|crewai|pydantic-ai)$",
    )
    system_prompt: str | None = None
    model_config_: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    tools: list[str] = Field(default_factory=list)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    is_public: bool = False
    is_platform: bool = False
    package_config: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Wheel package coordinates the agent-service uses to install "
            "this agent at startup. Required for wheel-delivered agents. "
            "Shape: {name, version, index_url?, entry_point}. "
            "When omitted, the agent is assumed to be code-baked into the "
            "agent-service image (legacy path)."
        ),
    )


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_type: str | None = Field(
        default=None,
        pattern=r"^(conversational|autonomous|reactive|research)$",
    )
    framework: str | None = Field(
        default=None,
        pattern=r"^(custom|langchain|autogen|crewai|pydantic-ai)$",
    )
    system_prompt: str | None = None
    model_config_: dict[str, Any] | None = Field(default=None, alias="model_config")
    tools: list[str] | None = None
    parameters_schema: dict[str, Any] | None = None
    default_parameters: dict[str, Any] | None = None
    tags: list[str] | None = None
    is_public: bool | None = None
    is_platform: bool | None = None
    package_config: dict[str, Any] | None = None


class AgentResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    agent_type: str
    framework: str
    system_prompt: str | None = None
    model_config_: dict[str, Any] = Field(alias="model_config")
    tools: list[str]
    parameters_schema: dict[str, Any]
    default_parameters: dict[str, Any]
    tags: list[str]
    is_public: bool
    is_platform: bool = False
    package_config: dict[str, Any] | None = None
    org_id: str
    created_by: str
    creator_name: str | None = None
    org_name: str | None = None


# --- Agentic Task ---


class AgenticTaskCreate(BaseModel):
    """Submit a new task within an agentic run."""

    agent_id: str
    task: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    agentic_run_id: str | None = None


class AgenticTaskResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str | None = None
    conversation_id: str | None = None
    status: str
    task: str
    context: dict[str, Any]
    result: dict[str, Any] | None = None
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    error_message: str | None = None
    tokens_used: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    org_id: str
    submitted_by: str


class AgenticTaskUpdate(BaseModel):
    """Update task status (used internally by the agent executor)."""

    status: str | None = Field(
        default=None,
        pattern=r"^(pending|running|completed|failed|cancelled)$",
    )
    error_message: str | None = None
    result: dict[str, Any] | None = None
    messages: list[dict[str, Any]] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tokens_used: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgenticTaskDetail(AgenticTaskResponse):
    """Task response with inline agent definition info."""

    agent_name: str
    agent_slug: str


# --- Agentic Run ---


class AgenticRunCreate(BaseModel):
    """Create a new agentic run session."""

    agent_id: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgenticRunUpdate(BaseModel):
    """Update an agentic run."""

    title: str | None = None


class AgenticRunResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    agent_id: str | None = None
    title: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    org_id: str
    created_by: str
    task_count: int = 0
    latest_task_status: str | None = None


class AgenticRunDetail(AgenticRunResponse):
    """Agentic run with its tasks included."""

    tasks: list[AgenticTaskResponse] = Field(default_factory=list)
