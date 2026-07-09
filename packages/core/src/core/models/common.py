"""Common Pydantic schemas shared across services."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# --- Base schemas ---


class TimestampSchema(BaseModel):
    created_at: datetime
    updated_at: datetime


# --- User schemas ---


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    org_id: str = Field(min_length=1, description="Organization ID is required")
    team_id: str | None = None
    role_name: str = "scientist"


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    team_id: str | None = None
    role_name: str | None = None


class UserResponse(UserBase, TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    is_active: bool
    org_id: str
    team_id: str | None = None
    role_id: str | None = None
    auth_method: str = "unknown"
    permissions: list[str] = []


class UserWithRoleResponse(UserResponse):
    role: str | None = None


# --- Org schemas ---


class OrgBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class OrgCreate(OrgBase):
    description: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class OrgUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    is_active: bool | None = None


class OrgResponse(OrgBase, TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    description: str | None = None
    settings: dict[str, Any]
    is_active: bool


# --- Team schemas ---


class TeamBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TeamCreate(TeamBase):
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="URL-safe identifier; auto-derived from name when omitted",
    )
    description: str | None = None


class TeamUpdate(BaseModel):
    name: str | None = None
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    description: str | None = None
    is_active: bool | None = None


class TeamResponse(TeamBase, TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    org_id: str
    description: str | None = None
    is_active: bool = True


# --- Auth schemas ---


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str  # user_id
    email: str
    role: str | None = None
    org_id: str | None = None
    team_id: str | None = None
    permissions: list[str] = []
    exp: datetime | None = None
    type: str = "access"  # "access" or "refresh"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    auth_method: str | None = (
        None  # "local" to force local DB auth, None to use configured provider
    )


class ChangePasswordRequest(BaseModel):
    """Request body for changing password (local auth users only)."""

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


# --- API Key schemas ---


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = None


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    scopes: list[str]
    is_active: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime


class ApiKeyCreated(ApiKeyResponse):
    """Returned only on creation — includes the full key (shown once)."""

    key: str


# --- Pagination ---


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    skip: int
    limit: int


# --- Admin schemas ---


class AdminUserCreate(UserCreate):
    """User creation payload for platform/org admins.

    Currently has no extra fields beyond ``UserCreate``; kept as a
    distinct type so admin endpoints can evolve independently of the
    self-registration payload.
    """


class AdminUserUpdate(BaseModel):
    """Extended user update for platform admins — includes org_id."""

    full_name: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    org_id: str | None = None
    team_id: str | None = None
    role_name: str | None = None


class AdminResetPassword(BaseModel):
    """Admin-initiated password reset for a local auth user."""

    new_password: str = Field(min_length=8, max_length=128)


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_orgs: int
    active_orgs: int
    total_teams: int
    total_roles: int
    total_llm_providers: int = 0
    default_llm_providers: int = 0
    total_buckets: int = 0
    default_buckets: int = 0
    total_compute_backends: int = 0
    enabled_compute_backends: int = 0
    total_artifacts: int = 0


class ServiceHealthResponse(BaseModel):
    name: str
    url: str
    status: str  # "healthy", "unhealthy", "unreachable"
    latency_ms: float | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    permissions: list[str]
    is_active: bool = True


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: str | None = None
    permissions: list[str] | None = None
    is_active: bool | None = None


# --- LLM Provider schemas ---


class LLMProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    provider_type: str = Field(
        default="openai_compatible",
        pattern=r"^(openai_compatible)$",
    )
    base_url: str | None = None
    api_key: str | None = Field(
        default=None,
        description="Plaintext API key to encrypt and store in the database",
    )
    default_model: str = Field(min_length=1, max_length=255)
    supported_models: list[str] = Field(default_factory=list)
    max_tokens: int | None = None
    is_default: bool = False
    org_id: str | None = Field(default=None, description="Override org (platform admin only)")


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_url: str | None = None
    api_key: str | None = Field(
        default=None,
        description="Plaintext API key to encrypt and store in the database",
    )
    default_model: str | None = None
    supported_models: list[str] | None = None
    max_tokens: int | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class LLMProviderResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    provider_type: str
    base_url: str | None = None
    has_api_key: bool = Field(
        default=False,
        description="Whether an encrypted API key is stored in the database",
    )
    default_model: str
    supported_models: list[str]
    max_tokens: int | None = None
    is_default: bool
    is_active: bool = True
    org_id: str
    org_name: str | None = None
    created_by: str


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    details: dict[str, Any]
    ip_address: str | None = None
    user_agent: str | None = None
    timestamp: datetime


class DockerContainerResponse(BaseModel):
    id: str
    name: str
    image: str
    status: str  # "running", "exited", "paused", etc.
    health: str | None = None  # "healthy", "unhealthy", "starting", None
    state: str
    created: str
    ports: list[str]


class ServiceLogsResponse(BaseModel):
    service_name: str
    logs: str


class DockerContainerLogsResponse(BaseModel):
    container_id: str
    container_name: str
    logs: str
