"""Pydantic schemas for datasets and dataset versions."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.models.common import TimestampSchema

# --- Dataset ---


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str | None = None
    data_type: str = Field(default="tabular", pattern=r"^(tabular|molecular|sequence|image|other)$")
    file_format: str | None = None
    tags: list[str] = Field(default_factory=list)
    data_schema: dict[str, Any] = Field(
        description=(
            "JSON Schema (draft) describing expected file structure. "
            "Required and must be a non-empty object — every dataset must "
            "declare its shape so uploads can be validated and downstream "
            "tools/pipelines can reason about the data."
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_public: bool = False

    @field_validator("data_schema")
    @classmethod
    def _data_schema_non_empty(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not v:
            raise ValueError("data_schema is required and must be a non-empty JSON Schema object")
        return v


class DatasetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    data_type: str | None = Field(
        default=None, pattern=r"^(tabular|molecular|sequence|image|other)$"
    )
    file_format: str | None = None
    tags: list[str] | None = None
    data_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    is_public: bool | None = None


class DatasetResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    slug: str
    description: str | None = None
    data_type: str
    file_format: str | None = None
    tags: list[str]
    data_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict, alias="metadata_", serialization_alias="metadata"
    )
    is_public: bool
    org_id: str
    created_by: str
    creator_name: str | None = None
    updated_by: str | None = None
    updated_by_name: str | None = None
    org_name: str | None = None
    version_count: int = 0
    latest_version: int | None = None
    latest_version_status: str | None = None
    total_size: int = 0
    total_file_count: int = 0


# --- Dataset Version ---


class DatasetVersionCreate(BaseModel):
    description: str | None = None


class DatasetFileInfo(BaseModel):
    """Metadata for a single file within a dataset version."""

    file_name: str
    file_size: int
    content_type: str
    storage_key: str
    checksum_sha256: str | None = None


class VersionTransferRequest(BaseModel):
    """Request body for transferring files from another bucket."""

    source_bucket_id: str = Field(description="ID of the registered ObjectStoreBucket")
    file_paths: list[str] = Field(
        min_length=1,
        description="File paths (keys) within the source bucket to transfer",
    )
    description: str | None = None


class DatasetVersionResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    version: int
    description: str | None = None
    status: str
    created_by: str
    creator_name: str | None = None
    updated_by: str | None = None
    updated_by_name: str | None = None
    storage_bucket: str
    files: list[DatasetFileInfo] = Field(default_factory=list)
    transfer_method: str | None = None
    source_bucket_id: str | None = None
    source_files: list[str] | None = None


class DatasetWithVersions(DatasetResponse):
    """Dataset response including its version history."""

    versions: list[DatasetVersionResponse] = Field(default_factory=list)


class DatasetSearchParams(BaseModel):
    """Query parameters for dataset search."""

    q: str | None = None
    data_type: str | None = None
    tags: list[str] | None = None
    org_id: str | None = None
    is_public: bool | None = None
    skip: int = 0
    limit: int = 50
