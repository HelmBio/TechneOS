"""ObjectStoreBucket model — registered S3-compatible storage buckets.

Each bucket belongs to an organization and can point to any S3-compatible
endpoint (MinIO, AWS S3, GCS, etc.). Access credentials are stored as
Fernet-encrypted values at rest.
"""

from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from core.models import Base, TimestampMixin, UUIDMixin
from core.models.user import Org, User  # noqa: F401 — register for relationship resolution


class ObjectStoreBucket(Base, UUIDMixin, TimestampMixin):
    """A registered S3-compatible bucket accessible to an organization.

    Each bucket may use its own endpoint and credentials, allowing the
    platform to read from (or write to) external object stores.
    """

    __tablename__ = "object_store_buckets"

    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

    # Actual bucket name in the external object store
    bucket_name = Column(String(255), nullable=False)

    # Connection details — None means use the platform's default MinIO
    endpoint_url = Column(
        String(500),
        nullable=True,
        comment="S3-compatible endpoint URL; None = use platform default",
    )
    region = Column(String(100), nullable=True, comment="AWS region or equivalent")
    secure = Column(Boolean, default=True, nullable=False, comment="Use TLS (HTTPS)")

    # Encrypted credentials — None means use the platform's default credentials
    encrypted_access_key = Column(
        Text,
        nullable=True,
        comment="Fernet-encrypted access key stored at rest",
    )
    encrypted_secret_key = Column(
        Text,
        nullable=True,
        comment="Fernet-encrypted secret key stored at rest",
    )

    is_default = Column(Boolean, default=False, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Ownership — linked to an organization
    org_id = Column(String(36), ForeignKey("orgs.id"), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Relationships
    org = relationship("Org", lazy="joined")
    creator = relationship("User", lazy="joined")
