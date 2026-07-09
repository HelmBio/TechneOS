"""Pydantic schemas for Apps and AppLaunches."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.models.common import TimestampSchema

LaunchMode = Literal["external", "embedded"]
AuthMode = Literal["none", "oidc", "signed_jwt"]
RuntimeStatus = Literal["pending", "building", "deploying", "active", "failed", "stopped"]
AppStatus = Literal["draft", "active", "deprecated"]
AppCategory = Literal[
    "visualization", "notebook", "editor", "data-browser", "ml-playground", "general"
]


class AppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    category: AppCategory = "general"
    tags: list[str] = Field(default_factory=list)
    icon_url: str | None = Field(default=None, max_length=512)
    thumbnail_url: str | None = Field(default=None, max_length=512)

    launch_mode: LaunchMode

    # external mode
    external_url: str | None = Field(default=None, max_length=1024)

    # embedded mode (Docker)
    docker_image: str | None = Field(default=None, max_length=512)
    docker_tag: str | None = Field(default="latest", max_length=128)
    container_port: int | None = Field(default=None, ge=1, le=65535)
    env: dict[str, str] = Field(default_factory=dict)
    resource_requirements: dict[str, Any] = Field(default_factory=dict)
    health_check_path: str | None = Field(default="/", max_length=255)
    embed_sandbox: str | None = Field(default=None, max_length=255)
    embed_allow: str | None = Field(default=None, max_length=255)

    # auth handoff
    auth_mode: AuthMode = "none"
    oidc_client_id: str | None = Field(default=None, max_length=255)
    launch_token_audience: str | None = Field(default=None, max_length=255)
    launch_token_ttl_seconds: int | None = Field(default=300, ge=10, le=3600)

    status: AppStatus = "draft"
    is_public: bool = False

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "AppCreate":
        if self.launch_mode == "external":
            if not self.external_url:
                raise ValueError("external_url is required when launch_mode='external'")
        else:  # embedded
            missing = [
                f
                for f, v in {
                    "docker_image": self.docker_image,
                    "container_port": self.container_port,
                }.items()
                if not v
            ]
            if missing:
                raise ValueError(f"embedded App requires: {', '.join(missing)}")
        if self.auth_mode == "oidc" and not self.oidc_client_id:
            raise ValueError("oidc_client_id is required when auth_mode='oidc'")
        if self.auth_mode == "signed_jwt" and not self.launch_token_audience:
            raise ValueError("launch_token_audience is required when auth_mode='signed_jwt'")
        return self


class AppUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: AppCategory | None = None
    tags: list[str] | None = None
    icon_url: str | None = None
    thumbnail_url: str | None = None
    external_url: str | None = None
    docker_image: str | None = None
    docker_tag: str | None = None
    container_port: int | None = Field(default=None, ge=1, le=65535)
    env: dict[str, str] | None = None
    resource_requirements: dict[str, Any] | None = None
    health_check_path: str | None = None
    embed_sandbox: str | None = None
    embed_allow: str | None = None
    auth_mode: AuthMode | None = None
    oidc_client_id: str | None = None
    launch_token_audience: str | None = None
    launch_token_ttl_seconds: int | None = Field(default=None, ge=10, le=3600)
    status: AppStatus | None = None
    is_public: bool | None = None


class AppResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    category: str
    tags: list[str]
    icon_url: str | None = None
    thumbnail_url: str | None = None

    launch_mode: str
    external_url: str | None = None
    docker_image: str | None = None
    docker_tag: str | None = None
    container_port: int | None = None
    env: dict[str, str] = Field(default_factory=dict)
    resource_requirements: dict[str, Any] = Field(default_factory=dict)
    health_check_path: str | None = None
    embed_sandbox: str | None = None
    embed_allow: str | None = None
    runtime_status: str
    runtime_endpoint: str | None = None
    last_deployed_at: datetime | None = None
    last_build_error: str | None = None

    auth_mode: str
    oidc_client_id: str | None = None
    launch_token_audience: str | None = None
    launch_token_ttl_seconds: int | None = None

    status: str
    is_public: bool
    org_id: str
    created_by: str
    creator_name: str | None = None
    updated_by: str | None = None
    updated_by_name: str | None = None
    org_name: str | None = None


class AppLaunchResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    app_id: str
    org_id: str
    launched_by: str
    launcher_name: str | None = None
    launch_mode: str
    auth_mode: str
    client_ip: str | None = None
    user_agent: str | None = None


class AppLaunchResult(BaseModel):
    """Payload returned by POST /apps/{id}/launch."""

    launch_mode: str
    launch_url: str
    auth_mode: str
    token: str | None = None
    expires_at: datetime | None = None
