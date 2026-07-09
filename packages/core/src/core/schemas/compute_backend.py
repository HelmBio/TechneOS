"""Pydantic schemas for compute backends."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema


class ComputeBackendCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=100)
    backend_type: str = Field(min_length=1, max_length=50)
    description: str | None = None
    status: str = "disabled"
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class ComputeBackendUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    status: str | None = None
    config: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None


class ComputeBackendResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    display_name: str
    backend_type: str
    description: str | None = None
    status: str
    config: dict[str, Any]
    capabilities: dict[str, Any]
