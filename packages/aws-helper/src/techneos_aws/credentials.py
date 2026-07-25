"""boto3 client factory — one place for region (and future role/retry) config.

AWS credentials are resolved by boto3 from the environment: the EC2 instance
role in prod, local AWS config in dev. The region comes from ``AWS_REGION``
(default ``us-east-1``). Centralizing construction keeps ECR and CodeArtifact
consistent instead of ad-hoc ``boto3.client(...)`` calls scattered per service.
"""

from __future__ import annotations

import os

import boto3


def client(service_name: str, region: str | None = None):
    """Return a boto3 client for ``service_name``.

    ``region`` overrides the default (``AWS_REGION``, else ``us-east-1``) — the
    worker pulls ECR images whose region is encoded in the image URL, which may
    differ from the ambient region.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client(service_name, region_name=region)
