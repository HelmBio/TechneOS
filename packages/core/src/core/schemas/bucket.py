"""Pydantic schemas for ObjectStoreBucket CRUD."""

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema


class BucketCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    bucket_name: str = Field(min_length=1, max_length=255)
    endpoint_url: str | None = None
    org_id: str | None = Field(
        default=None, description="Required for admin create; org-scoped routes use URL param"
    )
    region: str | None = None
    secure: bool = True
    access_key: str | None = Field(
        default=None,
        description="Plaintext access key to encrypt and store in the database",
    )
    secret_key: str | None = Field(
        default=None,
        description="Plaintext secret key to encrypt and store in the database",
    )
    is_default: bool = False


class BucketUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    bucket_name: str | None = None
    endpoint_url: str | None = None
    region: str | None = None
    secure: bool | None = None
    access_key: str | None = Field(
        default=None,
        description="Plaintext access key to encrypt and store in the database",
    )
    secret_key: str | None = Field(
        default=None,
        description="Plaintext secret key to encrypt and store in the database",
    )
    is_default: bool | None = None
    is_active: bool | None = None


class BucketResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    bucket_name: str
    endpoint_url: str | None = None
    region: str | None = None
    secure: bool = True
    has_access_key: bool = Field(
        default=False,
        description="Whether an encrypted access key is stored in the database",
    )
    has_secret_key: bool = Field(
        default=False,
        description="Whether an encrypted secret key is stored in the database",
    )
    is_default: bool
    is_active: bool = True
    org_id: str
    org_name: str | None = None
    created_by: str
