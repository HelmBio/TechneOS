"""App and AppLaunch models — registered interactive web applications."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="general",
        comment="visualization | notebook | editor | data-browser | ml-playground | general",
    )
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # --- Launch ---
    launch_mode: Mapped[str] = mapped_column(
        Enum("external", "embedded", name="app_launch_mode"),
        nullable=False,
        comment="external | embedded",
    )
    # External-mode fields
    external_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Embedded-mode fields
    docker_image: Mapped[str | None] = mapped_column(String(512), nullable=True)
    docker_tag: Mapped[str | None] = mapped_column(String(128), nullable=True, default="latest")
    container_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    env: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resource_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    health_check_path: Mapped[str | None] = mapped_column(String(255), nullable=True, default="/")
    embed_sandbox: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embed_allow: Mapped[str | None] = mapped_column(String(255), nullable=True)
    runtime_status: Mapped[str] = mapped_column(
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
    runtime_endpoint: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="internal host:port the gateway proxies to; written by deployer",
    )
    last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_build_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Auth handoff ---
    auth_mode: Mapped[str] = mapped_column(
        Enum("none", "oidc", "signed_jwt", name="app_auth_mode"),
        nullable=False,
        default="none",
    )
    oidc_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    launch_token_audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    launch_token_ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, default=300)

    # --- Lifecycle / ownership ---
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "deprecated", name="app_status"),
        nullable=False,
        default="draft",
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

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

    app_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    launched_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    launch_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="snapshot of App.launch_mode at launch"
    )
    auth_mode: Mapped[str] = mapped_column(String(20), nullable=False, comment="snapshot of App.auth_mode at launch")
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # --- Relationships ---
    app = relationship("App", back_populates="launches")
    launcher = relationship("User", foreign_keys=[launched_by], lazy="joined")

    @property
    def launcher_name(self) -> str | None:
        return self.launcher.full_name if self.launcher else None
