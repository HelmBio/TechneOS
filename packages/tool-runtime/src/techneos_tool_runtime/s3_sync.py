"""S3 ↔ /work sync for AWS Batch execution.

When ``TECHNEOS_BATCH_WORK_BUCKET`` is set, the tool is running on AWS Batch
where no bind-mount is available. The worker staged the work directory
to S3 before submitting the job; this module downloads it to the
container's local ``/work`` at startup and uploads ``/work/output/``
back to S3 after the tool finishes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def s3_sync_enabled() -> bool:
    return bool(os.environ.get("TECHNEOS_BATCH_WORK_BUCKET"))


def download_work_dir(work_root: Path) -> None:
    """Download the work directory from S3 to the local filesystem."""
    import boto3

    bucket = os.environ["TECHNEOS_BATCH_WORK_BUCKET"]
    prefix = os.environ.get("TECHNEOS_S3_WORK_PREFIX", "")
    if not prefix:
        logger.warning("download_work_dir: TECHNEOS_S3_WORK_PREFIX is empty; skipping download")
        return

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix) + 1:]
            if not rel:
                continue
            local_path = work_root / rel
            local_path.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(local_path))

    logger.info("Downloaded s3://%s/%s → %s", bucket, prefix, work_root)


def upload_outputs(work_root: Path) -> None:
    """Upload /work/output/ back to S3."""
    import boto3

    bucket = os.environ["TECHNEOS_BATCH_WORK_BUCKET"]
    prefix = os.environ.get("TECHNEOS_S3_WORK_PREFIX", "")
    if not prefix:
        return

    output_dir = work_root / "output"
    if not output_dir.exists():
        return

    s3 = boto3.client("s3")
    count = 0
    for file_path in output_dir.rglob("*"):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(work_root).as_posix()
        s3_key = f"{prefix}/{rel}"
        s3.upload_file(str(file_path), bucket, s3_key)
        count += 1

    logger.info("Uploaded %d output file(s) → s3://%s/%s/output/", count, bucket, prefix)
