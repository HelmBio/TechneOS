"""Agent definition, agentic run, and task models."""

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401  — register for relationship resolution


class AgenticRun(Base, UUIDMixin, TimestampMixin):
    """An agentic run session with an agent.

    Groups multiple AgenticTasks together to maintain conversational context.
    """

    __tablename__ = "agent_runs"

    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title = Column(String(500), nullable=True, comment="optional run title")
    summary = Column(Text, nullable=True, comment="auto-generated summary of run")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

    # Ownership
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    agent = relationship("AgentDefinition", back_populates="agentic_runs")
    tasks = relationship(
        "AgenticTask", back_populates="agentic_run", order_by="AgenticTask.created_at"
    )


class AgentDefinition(Base, UUIDMixin, TimestampMixin):
    """A reusable AI agent definition.

    Stores the agent's configuration including its type, framework,
    system prompt, model settings, and the tools it can invoke.
    """

    __tablename__ = "agents"

    name = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    agent_type = Column(
        String(50),
        nullable=False,
        default="conversational",
        comment="conversational | autonomous | reactive",
    )
    framework = Column(
        String(50),
        nullable=False,
        default="custom",
        comment="custom | langchain | autogen | crewai",
    )
    system_prompt = Column(Text, nullable=True)

    # Model configuration (model name, temperature, etc.)
    model_config_ = Column("model_config", JSONB, nullable=False, default=dict)

    # Tools this agent can use (list of tool slugs)
    tools = Column(JSONB, nullable=False, default=list)

    # Parameter schemas and defaults
    parameters_schema = Column(JSONB, nullable=False, default=dict)
    default_parameters = Column(JSONB, nullable=False, default=dict)

    tags = Column(JSONB, nullable=False, default=list)
    is_public = Column(Boolean, default=False, nullable=False)
    is_platform = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
        comment="Platform-level agent (excluded from user agent listings)",
    )

    # Where the agent's Python package lives (wheel published to DevPI/CodeArtifact).
    # When set, the agent-service installs this package at startup before
    # enumerating `techneos.agents` entry points. When NULL, the agent is assumed
    # to be code-baked (legacy path — the package is COPYed into the
    # agent-service image). Shape:
    #   {"name": "chembl-agent", "version": "0.1.0",
    #    "index_url": "http://devpi:8080/...",  # optional, falls back to PYTHON_PACKAGE_INDEX_URL
    #    "entry_point": "chembl_agent"}          # python entry-point group `techneos.agents`
    package_config = Column(
        JSONB,
        nullable=True,
        comment="Wheel package coords for runtime install (name, version, index_url, entry_point)",
    )

    # Append-only log of timestamped definition snapshots (the version-relevant
    # fields: system_prompt, model_config, tools, parameters_schema,
    # default_parameters, package_config). One entry is appended whenever those
    # fields change (e.g. on re-register). The platform always uses the latest
    # definition (the live columns above); this preserves history and is shaped to
    # mirror a future agent_versions row, so a later agents/agent_versions split is
    # a straight projection.
    version_history = Column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="Append-only [{version, captured_at, ...definition snapshot}] log",
    )

    # Ownership
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    tasks = relationship("AgenticTask", back_populates="agent", cascade="all, delete-orphan")
    agentic_runs = relationship("AgenticRun", back_populates="agent", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    org = relationship("Org", foreign_keys=[org_id], lazy="joined")

    @property
    def creator_name(self) -> str | None:
        """Resolved creator full name for API responses."""
        return self.creator.full_name if self.creator else None

    @property
    def org_name(self) -> str | None:
        """Resolved organization name for API responses."""
        return self.org.name if self.org else None


class AgenticTask(Base, UUIDMixin, TimestampMixin):
    """A single task execution within an agentic run.

    Tracks the task, reasoning trace, tool invocations,
    and final result for a given task.
    """

    __tablename__ = "agent_task_runs"

    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    agentic_run_id = Column(
        "conversation_id",
        String(36),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="links this task to an agentic run session",
    )

    # Runtime
    status: Column[str] = Column(
        Enum(
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
            name="agent_run_status",
        ),
        nullable=False,
        default="pending",
    )
    task = Column(Text, nullable=False, comment="the user's task or prompt")
    context = Column(
        JSONB, nullable=False, default=dict, comment="input context (dataset refs, params, etc.)"
    )
    result = Column(JSONB, nullable=True, comment="structured result from the agent")
    messages = Column(
        JSONB, nullable=False, default=list, comment="conversation history / reasoning trace"
    )
    tool_calls = Column(JSONB, nullable=False, default=list, comment="log of tool invocations")
    error_message = Column(Text, nullable=True)
    tokens_used = Column(Integer, nullable=True)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Who launched it
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    agent = relationship("AgentDefinition", back_populates="tasks")
    agentic_run = relationship("AgenticRun", back_populates="tasks")
