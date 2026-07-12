"""ECR auth for image pulls in the Airflow worker's Docker backend.

Worker-runtime AWS code (like :mod:`operators.codeartifact`): it runs only in
the Airflow worker container, which carries the EC2 IAM role. When a tool's
image is an ECR URL, the worker's docker-py SDK must supply credentials with the
pull — the host's ``amazon-ecr-credential-helper`` is a *client-side* mechanism
for the host ``docker`` CLI and does **not** apply to docker-py talking to the
daemon socket from inside the container. So we mint a short-lived ECR token here
and hand it to ``images.pull`` as ``auth_config``.
"""

from __future__ import annotations

import base64
import logging

import boto3

logger = logging.getLogger(__name__)


def _is_ecr_image(image: str) -> bool:
    """True if ``image`` is an ECR registry reference needing AWS auth."""
    return ".dkr.ecr." in image and ".amazonaws.com" in image


def get_ecr_auth_config(image: str) -> dict[str, str] | None:
    """Return ``{"username", "password"}`` for an ECR image, else ``None``.

    Mints a fresh token via the worker's IAM role. Returns ``None`` for
    non-ECR images (local ``techneos/<slug>`` etc.) or on any failure, so the caller
    can fall back to an unauthenticated pull / cached image rather than crash.
    """
    if not _is_ecr_image(image):
        return None
    try:
        # registry host: <account>.dkr.ecr.<region>.amazonaws.com
        registry = image.split("/", 1)[0]
        region = registry.split(".")[3]
        client = boto3.client("ecr", region_name=region)
        resp = client.get_authorization_token()
        data = resp["authorizationData"][0]
        # authorizationToken is base64("AWS:<password>")
        token = base64.b64decode(data["authorizationToken"]).decode("utf-8")
        username, password = token.split(":", 1)
        return {"username": username, "password": password}
    except Exception as e:
        logger.warning("Failed to mint ECR auth for %s: %s", image, e)
        return None
