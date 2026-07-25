"""ECR auth for image pulls in the Airflow worker's Docker backend.

Worker-runtime glue over :mod:`techneos_aws.ecr`: it runs only in the Airflow
worker container, which carries the EC2 IAM role. When a tool's image is an ECR
URL, the worker's docker-py SDK must supply credentials with the pull — the
host's ``amazon-ecr-credential-helper`` is a *client-side* mechanism for the
host ``docker`` CLI and does **not** apply to docker-py talking to the daemon
socket from inside the container. So we mint a short-lived ECR token (for the
image's own region) and hand it to ``images.pull`` as ``auth_config``.
"""

from __future__ import annotations

import logging

from techneos_aws import ecr

logger = logging.getLogger(__name__)


def get_ecr_auth_config(image: str) -> dict[str, str] | None:
    """Return ``{"username", "password"}`` for an ECR image, else ``None``.

    Mints a fresh token via the worker's IAM role, for the region encoded in the
    image URL. Returns ``None`` for non-ECR images (local ``techneos/<slug>`` etc.)
    or on any failure, so the caller can fall back to an unauthenticated pull /
    cached image rather than crash.
    """
    if not ecr.is_ecr_registry(image):
        return None
    try:
        # registry host: <account>.dkr.ecr.<region>.amazonaws.com
        region = image.split("/", 1)[0].split(".")[3]
        user, password = ecr.mint_credentials(region=region)
        return {"username": user, "password": password}
    except Exception as e:
        logger.warning("Failed to mint ECR auth for %s: %s", image, e)
        return None
