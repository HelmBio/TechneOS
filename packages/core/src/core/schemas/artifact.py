"""Pydantic schemas for the compute artifact inventory."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models.common import TimestampSchema

_KIND_PATTERN = r"^(wheel|docker_image)$"
_ORIGIN_PATTERN = r"^(catalog|platform|other)$"
_STATUS_PATTERN = r"^(available|deprecated|deleted)$"


class ArtifactRegister(BaseModel):
    """Upsert payload — recorded by build scripts after a successful publish.

    Idempotent on (kind, name, version, registry_url): re-registering updates
    digest / source_commit_sha / published_at in place.
    """

    kind: str = Field(pattern=_KIND_PATTERN)
    origin: str = Field(default="other", pattern=_ORIGIN_PATTERN)
    name: str = Field(min_length=1, max_length=512)
    version: str = Field(min_length=1, max_length=256)
    registry_url: str | None = Field(default=None, max_length=512)
    digest: str | None = Field(default=None, max_length=256)
    size_bytes: int | None = None
    source_commit_sha: str | None = Field(default=None, max_length=64)
    source_repo: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactUpdate(BaseModel):
    """Mutate inventory state — e.g. deprecate or restore an artifact."""

    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None


class ArtifactResponse(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    origin: str
    name: str
    version: str
    registry_url: str | None = None
    digest: str | None = None
    size_bytes: int | None = None
    source_commit_sha: str | None = None
    source_repo: str | None = None
    status: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_", default_factory=dict)
    published_at: datetime | None = None
    published_by: str | None = None
