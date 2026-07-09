"""Dataset and DatasetVersion models."""

from typing import cast

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401  — register for relationship resolution


class Dataset(Base, UUIDMixin, TimestampMixin):
    """A dataset registered on the platform.

    Datasets are versioned — each upload creates a new DatasetVersion.
    Metadata (schema info, statistics, tags) is stored as JSONB.
    The actual data files live in object storage (MinIO).
    """

    __tablename__ = "datasets"

    name = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    data_type = Column(
        String(50),
        nullable=False,
        default="tabular",
        comment="tabular | molecular | sequence | image | other",
    )
    file_format = Column(
        String(50),
        nullable=True,
        default="csv",
        comment="csv | tsv | sdf | pdb | fasta | parquet | other",
    )
    tags = Column(JSONB, nullable=False, default=list)
    data_schema = Column(
        JSONB,
        nullable=True,
        comment="JSON Schema (draft) describing the expected structure of data files",
    )
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    is_public = Column(Boolean, default=False, nullable=False)

    # Ownership
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Relationships
    versions = relationship(
        "DatasetVersion", back_populates="dataset", cascade="all, delete-orphan"
    )
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = relationship("User", foreign_keys=[updated_by], lazy="joined")
    org = relationship("Org", foreign_keys=[org_id], lazy="joined")

    @property
    def creator_name(self) -> str | None:
        """Resolved creator full name for API responses."""
        return self.creator.full_name if self.creator else None

    @property
    def updated_by_name(self) -> str | None:
        """Resolved updater full name for API responses."""
        return self.updater.full_name if self.updater else None

    @property
    def org_name(self) -> str | None:
        """Resolved organization name for API responses."""
        return self.org.name if self.org else None

    @property
    def version_count(self) -> int:
        """Number of versions for this dataset."""
        return len(self.versions) if self.versions else 0

    @property
    def latest_version(self) -> int | None:
        """Highest version number, or None if no versions exist."""
        if not self.versions:
            return None
        return cast(int | None, max(v.version for v in self.versions))

    @property
    def latest_version_status(self) -> str | None:
        """Status of the highest version, or None if no versions exist."""
        if not self.versions:
            return None
        latest = max(self.versions, key=lambda v: v.version)
        return cast(str | None, latest.status)

    @property
    def total_size(self) -> int:
        """Total file size across all versions."""
        total = 0
        for v in self.versions or []:
            files = getattr(v, "files", None) or []
            if files:
                total += sum(f.get("file_size", 0) for f in files)
            else:
                total += getattr(v, "file_size", 0)
        return total

    @property
    def total_file_count(self) -> int:
        """Total file count across all versions."""
        count = 0
        for v in self.versions or []:
            files = getattr(v, "files", None) or []
            count += len(files)
        return count


class DatasetVersion(Base, UUIDMixin, TimestampMixin):
    """An immutable snapshot of a dataset.

    Each version tracks the object store bucket, file metadata (stored in
    the `files` JSONB array), and upload status.
    """

    __tablename__ = "dataset_versions"

    dataset_id = Column(
        String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False)  # monotonically increasing per dataset
    description = Column(Text, nullable=True)

    # Object store bucket (same for all files in a version)
    storage_bucket = Column(String(255), nullable=False)

    # Multiple files within this version (array of {file_name, file_size, content_type, storage_key, checksum_sha256})
    files = Column(JSONB, nullable=False, default=list)

    # Transfer tracking
    transfer_method = Column(
        String(50),
        nullable=True,
        comment="How files were added: 'upload' (direct upload) or 'transfer' (copied from another bucket)",
    )
    source_bucket_id = Column(
        String(36),
        ForeignKey("object_store_buckets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_files = Column(
        JSONB,
        nullable=True,
        comment="Original file paths/keys in the source bucket (list of strings)",
    )

    # Status
    status: Column[str] = Column(
        Enum("uploading", "processing", "ready", "failed", name="dataset_version_status"),
        nullable=False,
        default="uploading",
    )

    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Relationships
    dataset = relationship("Dataset", back_populates="versions")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = relationship("User", foreign_keys=[updated_by], lazy="joined")

    @property
    def creator_name(self) -> str | None:
        """Resolved creator full name for API responses."""
        return self.creator.full_name if self.creator else None

    @property
    def updated_by_name(self) -> str | None:
        """Resolved updater full name for API responses."""
        return self.updater.full_name if self.updater else None
