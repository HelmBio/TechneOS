"""ObjectStoreBucket model — registered S3-compatible storage buckets.

Each bucket belongs to an organization and can point to any S3-compatible
endpoint (MinIO, AWS S3, GCS, etc.). Access credentials are stored as
Fernet-encrypted values at rest.
"""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401 — register for relationship resolution


class ObjectStoreBucket(Base, UUIDMixin, TimestampMixin):
    """A registered S3-compatible bucket accessible to an organization.

    Each bucket may use its own endpoint and credentials, allowing the
    platform to read from (or write to) external object stores.
    """

    __tablename__ = "object_store_buckets"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Actual bucket name in the external object store
    bucket_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Connection details — None means use the platform's default MinIO
    endpoint_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="S3-compatible endpoint URL; None = use platform default",
    )
    region: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="AWS region or equivalent")
    secure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="Use TLS (HTTPS)")

    # Encrypted credentials — None means use the platform's default credentials
    encrypted_access_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Fernet-encrypted access key stored at rest",
    )
    encrypted_secret_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Fernet-encrypted secret key stored at rest",
    )

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Ownership — linked to an organization
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    org = relationship("Org", lazy="joined")
    creator = relationship("User", lazy="joined")
