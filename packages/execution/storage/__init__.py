"""Lightweight MinIO/S3 helper for the worker package.

This module is self-contained — it reads connection details from
environment variables so it works inside the Airflow container
without importing the ``core`` package.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from io import BytesIO
from typing import BinaryIO

from minio import Minio

logger = logging.getLogger(__name__)

# ── Configuration from environment ──────────────────────────────────

_MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
_MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
_MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
_MINIO_BUCKET = os.getenv("MINIO_BUCKET", "techneos-data")
_MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() in ("true", "1", "yes")

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            _MINIO_ENDPOINT,
            access_key=_MINIO_ACCESS_KEY,
            secret_key=_MINIO_SECRET_KEY,
            secure=_MINIO_SECURE,
        )
    return _client


def _ensure_bucket(bucket: str) -> None:
    client = _get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def download_file(
    storage_key: str,
    dest_path: str,
    bucket: str | None = None,
) -> str:
    """Download an object from MinIO to a local file path.

    Parameters
    ----------
    storage_key : str
        The object key inside the bucket, e.g.
        ``"datasets/{slug}/v1/compounds.csv"``.
    dest_path : str
        Local filesystem path to write the file to.  Parent directories
        must already exist.
    bucket : str, optional
        Override the default bucket.

    Returns
    -------
    str
        The *dest_path* (for convenience).
    """
    bucket = bucket or _MINIO_BUCKET
    client = _get_client()
    client.fget_object(bucket, storage_key, dest_path)
    logger.info("Downloaded %s/%s → %s", bucket, storage_key, dest_path)
    return dest_path


def upload_artifact(
    run_id: str,
    step_name: str,
    file_name: str,
    data: bytes | BinaryIO,
    content_type: str | None = None,
    bucket: str | None = None,
    resource_path: str = "pipeline-runs",
    key_prefix: str | None = None,
) -> dict:
    """Upload a file to MinIO and return metadata dict.

    Parameters
    ----------
    key_prefix : str, optional
        Full key prefix the caller has already composed — the storage key
        becomes ``{key_prefix}/{file_name}``. Orchestrators thread their
        run-specific prefix in here so artifacts land at
        ``pipeline-runs/{slug}/v{N}/{run_id}/{step}/...`` or
        ``tool-runs/{slug}/v{N}/{run_id}/...``.
    resource_path : str, optional
        Legacy fallback — used as ``{resource_path}/{run_id}/{step_name}``
        only when ``key_prefix`` isn't supplied. Kept so in-flight DAG
        runs from before this change don't blow up.

    Returns a dict with keys matching the ``PipelineRunArtifact`` model columns:
    ``storage_bucket``, ``storage_key``, ``file_name``, ``file_size``,
    ``content_type``, ``checksum_sha256``.
    """
    bucket = bucket or _MINIO_BUCKET
    _ensure_bucket(bucket)

    # Resolve content type
    if content_type is None:
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    # Normalise to bytes for hashing + length
    raw = data if isinstance(data, bytes) else data.read()

    file_size = len(raw)
    checksum = hashlib.sha256(raw).hexdigest()

    if key_prefix:
        storage_key = f"{key_prefix}/{file_name}"
    else:
        storage_key = f"{resource_path}/{run_id}/{step_name}/{file_name}"

    client = _get_client()
    client.put_object(
        bucket_name=bucket,
        object_name=storage_key,
        data=BytesIO(raw),
        length=file_size,
        content_type=content_type,
    )

    logger.info("Uploaded artifact %s/%s (%d bytes)", bucket, storage_key, file_size)

    return {
        "storage_bucket": bucket,
        "storage_key": storage_key,
        "file_name": file_name,
        "file_size": file_size,
        "content_type": content_type,
        "checksum_sha256": checksum,
    }
