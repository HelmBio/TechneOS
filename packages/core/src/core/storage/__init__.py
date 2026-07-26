"""Object storage abstraction — MinIO / S3-compatible implementation.

Supports both the platform's default object store and arbitrary external
endpoints via ``create_object_store()``.
"""

from typing import BinaryIO, Protocol, cast, runtime_checkable

from pydantic import BaseModel

from core.config import get_settings


class ObjectInfo(BaseModel):
    """Metadata about a stored object."""

    bucket: str
    key: str
    size: int
    content_type: str | None = None
    metadata: dict[str, str] = {}
    last_modified: str | None = None


@runtime_checkable
class ObjectStore(Protocol):
    """Abstract interface for object storage.

    Works with any S3-compatible backend (MinIO, AWS S3, GCS, etc.)
    """

    def put(
        self,
        bucket: str,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str: ...

    def get(self, bucket: str, key: str, max_bytes: int | None = None) -> bytes: ...

    def delete(self, bucket: str, key: str) -> None: ...

    def presigned_url(self, bucket: str, key: str, expires_seconds: int = 3600) -> str: ...

    def list_objects(self, bucket: str, prefix: str = "") -> list[ObjectInfo]: ...

    def ensure_bucket(self, bucket: str) -> None: ...

    def copy(
        self,
        source_bucket: str,
        source_key: str,
        dest_bucket: str,
        dest_key: str,
    ) -> str:
        """Copy an object from one location to another (server-side if possible)."""
        ...


class MinIOStore:
    """MinIO / S3-compatible object storage implementation.

    When created without arguments (the normal pattern), settings are loaded
    from ``Settings``.  Pass explicit arguments to target a different endpoint.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
    ) -> None:
        from minio import Minio

        settings = get_settings()

        self._endpoint = endpoint or settings.minio_endpoint
        self._access_key = access_key or settings.minio_access_key
        self._secret_key = secret_key or settings.minio_secret_key
        self._secure = settings.minio_secure if secure is None else secure
        self._default_bucket = settings.minio_bucket

        self._client = Minio(
            self._endpoint,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=self._secure,
        )

    def put(
        self,
        bucket: str,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload an object to the store."""
        self.ensure_bucket(bucket)
        self._client.put_object(
            bucket_name=bucket,
            object_name=key,
            data=data,
            length=length,
            content_type=content_type,
            metadata=cast("dict[str, str | list[str] | tuple[str]] | None", metadata),
        )
        return key

    def get(self, bucket: str, key: str, max_bytes: int | None = None) -> bytes:
        """Download an object from the store.

        If *max_bytes* is set, only the first *max_bytes* are returned
        (range GET).  This is useful for sampling file contents for
        schema validation without downloading the full object.
        """
        from core.exceptions import StorageError

        try:
            if max_bytes is not None:
                response = self._client.get_object(bucket, key, offset=0, length=max_bytes)
            else:
                response = self._client.get_object(bucket, key)
            return response.read()
        except Exception as e:
            raise StorageError(f"Failed to get object {bucket}/{key}: {e}") from e
        finally:
            if "response" in locals():
                response.close()
                response.release_conn()

    def delete(self, bucket: str, key: str) -> None:
        """Delete an object from the store."""
        self._client.remove_object(bucket, key)

    def presigned_url(self, bucket: str, key: str, expires_seconds: int = 3600) -> str:
        """Generate a presigned URL for temporary access.

        In production, MINIO_PUBLIC_ENDPOINT should be set to the public HTTPS
        hostname (e.g. ``techneosapi.example.com``) so the URL the browser fetches is
        reachable and uses HTTPS. The internal endpoint is used for all other
        operations; only presigning switches to the public one.
        """
        from datetime import timedelta

        settings = get_settings()
        if settings.minio_public_endpoint:
            from minio import Minio

            # The Minio client rejects an endpoint that carries a scheme
            # ("path in endpoint is not allowed"), but MINIO_PUBLIC_ENDPOINT is
            # naturally written as a URL (https://host). Accept either form:
            # strip a leading scheme, and let http:// downgrade to insecure.
            public_endpoint = settings.minio_public_endpoint
            secure = True
            if "://" in public_endpoint:
                scheme, public_endpoint = public_endpoint.split("://", 1)
                secure = scheme.lower() != "http"
            public_endpoint = public_endpoint.rstrip("/")

            # Signing-only client for the public endpoint. The region parameter
            # prevents Minio from making an HTTP request to determine the region,
            # which would fail against the nginx proxy (it's not a real MinIO).
            # We sign with the public endpoint so the URL is valid when accessed
            # from a browser, but we skip the region detection call.
            signing_client = Minio(
                public_endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=secure,
                region=settings.minio_region,
            )
        else:
            signing_client = self._client

        return signing_client.presigned_get_object(
            bucket, key, expires=timedelta(seconds=expires_seconds)
        )

    def list_objects(self, bucket: str, prefix: str = "") -> list[ObjectInfo]:
        """List objects in a bucket with optional prefix filter."""
        objects = self._client.list_objects(bucket, prefix=prefix, recursive=True)
        return [
            ObjectInfo(
                bucket=bucket,
                key=obj.object_name or "",
                size=obj.size or 0,
                content_type=obj.content_type,
                last_modified=str(obj.last_modified) if obj.last_modified else None,
            )
            for obj in objects
        ]

    def ensure_bucket(self, bucket: str) -> None:
        """Create bucket if it doesn't exist."""
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def copy(
        self,
        source_bucket: str,
        source_key: str,
        dest_bucket: str,
        dest_key: str,
    ) -> str:
        """Copy an object from one location to another (server-side copy).

        When source and destination are on the same MinIO server this is a
        fast server-side operation.  For heterogeneous endpoints the caller
        should fall back to get + put.
        """
        from minio.commonconfig import CopySource

        self.ensure_bucket(dest_bucket)
        self._client.copy_object(
            bucket_name=dest_bucket,
            object_name=dest_key,
            source=CopySource(source_bucket, source_key),
        )
        return dest_key


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    """Return the singleton object store (platform default)."""
    global _store
    if _store is None:
        _store = MinIOStore()
    return _store


def create_object_store(
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool = False,
) -> ObjectStore:
    """Create an object store client for an arbitrary S3-compatible endpoint.

    Useful for reading from (or writing to) external buckets registered
    by an organization.
    """
    return MinIOStore(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )
