"""App and AppLaunch models — registered interactive web applications."""

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401  — register for relationship resolution


class App(Base, UUIDMixin, TimestampMixin):
    """A registered interactive web application.

    Apps are launched in the browser. Two launch modes:
    - external: a URL elsewhere; platform opens it in a new tab
    - embedded: a Docker image hosted by the platform, rendered in an iframe
                at /apps/runtime/{slug}. The deployer worker pulls the image,
                starts a container, and writes runtime_endpoint when healthy.
    """

    __tablename__ = "apps"

    # --- Identity ---
    name = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(
        String(50),
        nullable=False,
        default="general",
        comment="visualization | notebook | editor | data-browser | ml-playground | general",
    )
    tags = Column(JSONB, nullable=False, default=list)
    icon_url = Column(String(512), nullable=True)
    thumbnail_url = Column(String(512), nullable=True)

    # --- Launch ---
    launch_mode: Column[str] = Column(
        Enum("external", "embedded", name="app_launch_mode"),
        nullable=False,
        comment="external | embedded",
    )
    # External-mode fields
    external_url = Column(String(1024), nullable=True)

    # Embedded-mode fields
    docker_image = Column(String(512), nullable=True)
    docker_tag = Column(String(128), nullable=True, default="latest")
    container_port = Column(Integer, nullable=True)
    env = Column(JSONB, nullable=False, default=dict)
    resource_requirements = Column(JSONB, nullable=False, default=dict)
    health_check_path = Column(String(255), nullable=True, default="/")
    embed_sandbox = Column(String(255), nullable=True)
    embed_allow = Column(String(255), nullable=True)
    runtime_status: Column[str] = Column(
        Enum(
            "pending",
            "building",
            "deploying",
            "active",
            "failed",
            "stopped",
            name="app_runtime_status",
        ),
        nullable=False,
        default="pending",
    )
    runtime_endpoint = Column(
        String(512),
        nullable=True,
        comment="internal host:port the gateway proxies to; written by deployer",
    )
    last_deployed_at = Column(DateTime(timezone=True), nullable=True)
    last_build_error = Column(Text, nullable=True)

    # --- Auth handoff ---
    auth_mode: Column[str] = Column(
        Enum("none", "oidc", "signed_jwt", name="app_auth_mode"),
        nullable=False,
        default="none",
    )
    oidc_client_id = Column(String(255), nullable=True)
    launch_token_audience = Column(String(255), nullable=True)
    launch_token_ttl_seconds = Column(Integer, nullable=True, default=300)

    # --- Lifecycle / ownership ---
    status: Column[str] = Column(
        Enum("draft", "active", "deprecated", name="app_status"),
        nullable=False,
        default="draft",
    )
    is_public = Column(Boolean, default=False, nullable=False)

    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # --- Relationships ---
    launches = relationship("AppLaunch", back_populates="app", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = relationship("User", foreign_keys=[updated_by], lazy="joined")
    org = relationship("Org", foreign_keys=[org_id], lazy="joined")

    @property
    def creator_name(self) -> str | None:
        return self.creator.full_name if self.creator else None

    @property
    def updated_by_name(self) -> str | None:
        return self.updater.full_name if self.updater else None

    @property
    def org_name(self) -> str | None:
        return self.org.name if self.org else None


class AppLaunch(Base, UUIDMixin, TimestampMixin):
    """Audit record written each time a user launches an App."""

    __tablename__ = "app_launches"

    app_id = Column(
        String(36), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    launched_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    launch_mode = Column(
        String(20), nullable=False, comment="snapshot of App.launch_mode at launch"
    )
    auth_mode = Column(String(20), nullable=False, comment="snapshot of App.auth_mode at launch")
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)

    # --- Relationships ---
    app = relationship("App", back_populates="launches")
    launcher = relationship("User", foreign_keys=[launched_by], lazy="joined")

    @property
    def launcher_name(self) -> str | None:
        return self.launcher.full_name if self.launcher else None
