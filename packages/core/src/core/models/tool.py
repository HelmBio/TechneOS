"""Tool and ToolVersion models — the tool registry."""

from typing import Any, cast

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401  — register for relationship resolution


class Tool(Base, UUIDMixin, TimestampMixin):
    """A registered computational tool (docking, scoring, ADMET, etc.).

    Tools are versioned — each version points to a Docker image or module script.
    The input/output schema is stored as JSONB for validation at runtime.

    tool_type determines how the tool is executed:
    - container: dedicated Docker image (default, for standalone services)
    - module: runs inside a shared language worker image (e.g., techneos/tool-runtime) (legacy, use pypi)
    - pypi: Python package pip-installed from a package index
    - api: external API endpoint
    - human: offline human task — creates an assignment for a user or team
    """

    __tablename__ = "tools"

    name = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(
        String(50),
        nullable=False,
        default="general",
        comment="docking | scoring | admet | ml | general | molecular-dynamics | quantum-chemistry | cheminformatics | bioinformatics | machine-learning | data-processing | other",
    )
    tool_type: Column[str] = Column(
        Enum("container", "module", "api", "pypi", "human", name="tool_type"),
        nullable=False,
        default="container",
        comment="container | module | pypi | human",
    )
    tags = Column(JSONB, nullable=False, default=list)
    is_public = Column(Boolean, default=False, nullable=False)

    # Tool-level documentation in Markdown. Moved here from tool_versions
    # because README describes the tool (what it does), not a specific
    # release; per-release notes live in tool_versions.changelog.
    readme = Column(Text, nullable=True, comment="Tool documentation in Markdown")

    # Ownership
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Relationships
    versions = relationship("ToolVersion", back_populates="tool", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = relationship("User", foreign_keys=[updated_by], lazy="joined")
    org = relationship("Org", foreign_keys=[org_id], lazy="joined")

    @property
    def creator_name(self) -> str | None:
        """Resolved creator full name for API responses."""
        return self.creator.full_name if self.creator else None

    @property
    def updated_by_name(self) -> str | None:
        """Resolved updater full name for API responses."""
        return self.updater.full_name if self.updater else None

    @property
    def org_name(self) -> str | None:
        """Resolved organization name for API responses."""
        return self.org.name if self.org else None

    @property
    def version_count(self) -> int:
        """Number of versions registered for this tool."""
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
    def runs(self) -> list[Any]:
        """All runs across all versions."""
        result: list[Any] = []
        for v in self.versions or []:
            result.extend(v.runs or [])
        return result

    @property
    def run_count(self) -> int:
        """Number of runs for this tool across all versions."""
        return len(self.runs)

    @property
    def last_run_status(self) -> str | None:
        """Status of the most recent run, or None if no runs exist."""
        all_runs = self.runs
        if not all_runs:
            return None
        latest = max(all_runs, key=lambda r: r.created_at)
        return cast(str | None, latest.status)


class ToolVersion(Base, UUIDMixin, TimestampMixin):
    """A specific version of a tool, tied to a Docker image or library spec."""

    __tablename__ = "tool_versions"

    tool_id = Column(
        String(36), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False)  # monotonically increasing per tool

    # NOTE: tool_script + script_environment columns were dropped by migration
    # y6z7a8b9c012 (the module tool_type's runtime path was removed in Phase 4;
    # the columns followed one release cycle later). Pypi-type version metadata
    # now lives entirely in the pypi_configs side-table.

    # Schema for pipeline validation — JSON (not JSONB) to preserve key order
    input_schema = Column(JSON, nullable=False, default=dict)
    output_schema = Column(JSON, nullable=False, default=dict)
    parameters_schema = Column(JSON, nullable=False, default=dict)

    # Resource requirements
    resource_requirements = Column(
        JSONB,
        nullable=False,
        default=dict,
        comment='e.g. {"cpu": "2", "memory": "4Gi", "gpu": 1}',
    )

    # Release info — per-version notes about what changed in this version.
    # Tool-level documentation lives in tools.readme.
    changelog = Column(
        Text, nullable=True, comment="Per-release notes — what changed in this version"
    )

    # Status
    status: Column[str] = Column(
        Enum("draft", "testing", "active", "deprecated", name="tool_version_status"),
        nullable=False,
        default="draft",
    )

    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Relationships
    tool = relationship("Tool", back_populates="versions")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = relationship("User", foreign_keys=[updated_by], lazy="joined")
    container_config = relationship(
        "ContainerConfig",
        back_populates="tool_version",
        uselist=False,
        lazy="joined",
        cascade="all, delete-orphan",
    )
    pypi_config = relationship(
        "PypiConfig",
        back_populates="tool_version",
        uselist=False,
        lazy="joined",
        cascade="all, delete-orphan",
    )
    human_config = relationship(
        "HumanConfig",
        back_populates="tool_version",
        uselist=False,
        lazy="joined",
        cascade="all, delete-orphan",
    )
    runs = relationship(
        "ToolRun",
        foreign_keys="ToolRun.tool_version_id",
        back_populates="tool_version",
        cascade="all, delete-orphan",
    )

    @property
    def creator_name(self) -> str | None:
        return self.creator.full_name if self.creator else None

    @property
    def updated_by_name(self) -> str | None:
        return self.updater.full_name if self.updater else None

    # Package fields are delegated to pypi_config (FK 1:1)
    @property
    def package_name(self) -> str | None:
        return self.pypi_config.package_name if self.pypi_config else None

    @property
    def package_version(self) -> str | None:
        return self.pypi_config.package_version if self.pypi_config else None

    @property
    def entry_point(self) -> str | None:
        return self.pypi_config.entry_point if self.pypi_config else None

    @property
    def package_index_url(self) -> str | None:
        return self.pypi_config.package_index_url if self.pypi_config else None

    @property
    def agent_tools(self) -> list[Any] | None:
        return self.pypi_config.agent_tools if self.pypi_config else None

    # Docker fields are delegated to container_config (FK 1:1)
    @property
    def docker_image(self) -> str | None:
        return self.container_config.docker_image if self.container_config else None

    @property
    def docker_tag(self) -> str | None:
        return self.container_config.docker_tag if self.container_config else None

    # Human config fields are delegated to human_config (FK 1:1)
    @property
    def assignment_type(self) -> str | None:
        return self.human_config.assignment_type if self.human_config else None

    @property
    def default_assignee(self) -> str | None:
        return self.human_config.default_assignee if self.human_config else None

    @property
    def due_in_hours(self) -> int | None:
        return self.human_config.due_in_hours if self.human_config else None

    @property
    def require_attachments(self) -> bool:
        return self.human_config.require_attachments if self.human_config else False

    @property
    def priority(self) -> str | None:
        return self.human_config.priority if self.human_config else None

    @property
    def default_project_lead_email(self) -> str | None:
        return self.human_config.default_project_lead_email if self.human_config else None


class ContainerConfig(Base, TimestampMixin):
    """Docker container configuration for container-type tool versions."""

    __tablename__ = "tool_docker_configs"

    tool_version_id = Column(
        String(36), ForeignKey("tool_versions.id", ondelete="CASCADE"), primary_key=True
    )
    docker_image = Column(String(512), nullable=False)
    docker_tag = Column(String(128), nullable=False, default="latest")
    # Lineage link to the inventory row; the string columns above remain
    # authoritative for execution (a version's definition freezes on first run).
    artifact_id = Column(
        String(36), ForeignKey("compute_artifacts.id", ondelete="SET NULL"), nullable=True
    )

    tool_version = relationship("ToolVersion", back_populates="container_config")


class PypiConfig(Base, TimestampMixin):
    """Python package configuration for pypi-type tool versions."""

    __tablename__ = "tool_pypi_configs"

    tool_version_id = Column(
        String(36), ForeignKey("tool_versions.id", ondelete="CASCADE"), primary_key=True
    )
    package_name = Column(String(255), nullable=False)
    package_version = Column(String(64), nullable=False)
    entry_point = Column(String(255), nullable=False)
    package_index_url = Column(String(512), nullable=True)
    # Lineage link to the inventory row; the package_name/version columns above
    # remain authoritative for execution (a version's definition freezes on run).
    artifact_id = Column(
        String(36), ForeignKey("compute_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    agent_tools = Column(
        JSONB,
        nullable=True,
        comment=(
            "List of async function names contributed to the Platform "
            "Assistant agent, e.g. ['calculate_molecule_properties']. "
            "Null means no agent-side tools."
        ),
    )

    tool_version = relationship("ToolVersion", back_populates="pypi_config")


class HumanConfig(Base, TimestampMixin):
    """Human-task configuration for human-type tool versions.

    Sibling of ``ContainerConfig`` and ``PypiConfig`` — the execution-type
    config sidecar for a human ``ToolVersion``. The runtime side of human
    tasks (TaskRun and its satellites) lives in task-service; this table
    stays in tool-service as part of the unified tool definition.
    """

    __tablename__ = "tool_human_configs"

    tool_version_id = Column(
        String(36), ForeignKey("tool_versions.id", ondelete="CASCADE"), primary_key=True
    )
    assignment_type = Column(
        String(50),
        nullable=False,
        default="team",
        comment="'user' for a specific user, 'team' for a team",
    )
    default_user_email = Column(
        String(255),
        nullable=True,
        comment="Default user assignee email (mutually exclusive with default_team_slug)",
    )
    default_team_slug = Column(
        String(255),
        nullable=True,
        comment="Default team assignee (mutually exclusive with default_user_email)",
    )
    due_in_hours = Column(
        Integer,
        nullable=True,
        default=72,
        comment="Default due time in hours from assignment creation",
    )
    require_attachments = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether submission requires file attachments",
    )
    priority = Column(
        String(20),
        nullable=False,
        default="medium",
        comment="Task priority: low, medium, high, or urgent",
    )
    default_project_lead_email = Column(
        String(255),
        nullable=True,
        comment="Optional project lead email (resolved to user UUID at task run creation)",
    )

    tool_version = relationship("ToolVersion", back_populates="human_config")

    @property
    def default_assignee(self) -> str | None:
        """Legacy single-string accessor.

        Returns the user email (when ``assignment_type='user'``) or team slug
        (when ``assignment_type='team'``) — whichever is set. New callers
        should read ``default_user_email`` / ``default_team_slug`` directly.
        """
        if self.assignment_type == "user":
            return cast("str | None", self.default_user_email)
        return cast("str | None", self.default_team_slug)


# Register ToolRun with SQLAlchemy's mapper registry. The string reference
# ``"ToolRun"`` in ToolVersion.runs needs the class loaded by the time
# configure_mappers() runs — but tool_run.py imports ToolVersion from us,
# so this has to happen at the bottom, after both classes above are
# defined. Without this, services that import only Tool/ToolVersion
# (e.g. auth's admin CRUD) fail to map ToolVersion at first use.
from core.models import tool_run  # noqa: E402,F401
