"""Pydantic schemas for LLM provider CRUD."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema


class LLMProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    provider_type: str = Field(
        default="openai_compatible",
        pattern=r"^(openai_compatible|google)$",
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


def llm_provider_response(p: Any) -> "LLMProviderResponse":
    """Build an LLMProviderResponse from an ORM model, including org_name."""
    data = LLMProviderResponse.model_validate(p)
    # Populate org_name from the eagerly-loaded relationship
    org = getattr(p, "org", None)
    if org is not None:
        data.org_name = getattr(org, "name", None)
    return data
