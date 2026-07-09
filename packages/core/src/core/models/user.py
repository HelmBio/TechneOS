"""User, Organization, Team, Role, and API Key models."""
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin


class Org(Base, UUIDMixin, TimestampMixin):
    """Organization — top-level tenant."""

    __tablename__ = "orgs"

    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    settings = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    teams = relationship("Team", back_populates="org", cascade="all, delete-orphan")
    users = relationship("User", back_populates="org")


class Team(Base, UUIDMixin, TimestampMixin):
    """Team within an organization."""

    __tablename__ = "teams"

    name = Column(String(255), nullable=False)
    slug = Column(
        String(255),
        nullable=False,
        index=True,
        comment="URL-safe identifier, unique within an org",
    )
    org_id = Column(String(36), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    org = relationship("Org", back_populates="teams")
    users = relationship("User", back_populates="team")


class Role(Base):
    """RBAC role with a set of permissions."""

    __tablename__ = "roles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    permissions = Column(JSONB, nullable=False, default=list)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    users = relationship("User", back_populates="role")


class User(Base, UUIDMixin, TimestampMixin):
    """Platform user account."""

    __tablename__ = "users"

    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=True)  # Null when using Keycloak
    is_active = Column(Boolean, default=True, nullable=False)

    # Foreign keys
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=True)
    role_id = Column(String(36), ForeignKey("roles.id"), nullable=True)

    # External identity provider ID (for Keycloak integration)
    external_id = Column(String(255), nullable=True, unique=True)

    # Relationships
    org = relationship("Org", back_populates="users")
    team = relationship("Team", back_populates="users")
    role = relationship("Role", back_populates="users")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")

    @property
    def auth_method(self) -> str:
        """Derive authentication method from stored credentials."""
        if self.hashed_password:
            return "local"
        return "sso"

    @property
    def permissions(self) -> list[str]:
        """Return permissions from the user's role."""
        if self.role:
            return self.role.permissions or []
        return []

    def to_dict(self) -> dict[str, Any]:
        """Return a dictionary representation of the User model."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "org_id": self.org_id,
            "team_id": self.team_id,
            "role_id": self.role_id,
            "auth_method": self.auth_method,
            "permissions": self.permissions,
        }


class ApiKey(Base, UUIDMixin, TimestampMixin):
    """API key for programmatic access."""

    __tablename__ = "api_keys"

    name = Column(String(255), nullable=False)
    prefix = Column(String(10), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scopes = Column(JSONB, nullable=False, default=list)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="api_keys")


class AuditLog(Base):
    """Audit log entry for compliance and debugging."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(50), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(36), nullable=True)
    details = Column(JSONB, nullable=False, default=dict)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
