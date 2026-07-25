"""ECR primitives — registry detection, repository creation, push/pull auth.

Pure boto3 helpers. The artifact publisher (image push) and the worker (image
pull) both mint short-lived ECR credentials here rather than each embedding
``get_authorization_token``.
"""

from __future__ import annotations

import base64
import logging
import time

from techneos_aws.credentials import client

logger = logging.getLogger(__name__)

# ECR authorization tokens are valid ~12h; cache (user, password) per region and
# refresh a few minutes early so a push/pull never uses a token that expires
# mid-flight. Keyed by region because the worker may pull cross-region images.
_TOKEN_TTL_SECONDS = 12 * 3600
_TOKEN_REFRESH_MARGIN_SECONDS = 300
_cred_cache: dict[str | None, tuple[str, str, float]] = {}


def is_ecr_registry(registry: str) -> bool:
    """True if ``registry`` (a host or a full image ref) is an ECR endpoint."""
    return ".dkr.ecr." in registry and "amazonaws.com" in registry


def ensure_repository(repo_name: str) -> None:
    """Create the ECR repository if it does not exist (idempotent)."""
    try:
        client("ecr").create_repository(repositoryName=repo_name)
        logger.info("Created ECR repository %s", repo_name)
    except Exception as exc:  # botocore ClientError, incl. AlreadyExists
        if exc.__class__.__name__ == "RepositoryAlreadyExistsException":
            return
        raise RuntimeError(f"could not ensure ECR repository {repo_name}: {exc}") from exc


def mint_credentials(region: str | None = None) -> tuple[str, str]:
    """Return (username, password) for the ECR registry, cached ~12h per region.

    ECR's authorization token is base64(``AWS:<password>``); the username is
    always ``AWS``. ``region`` defaults to the ambient AWS_REGION; the worker
    passes the region parsed from the image URL for a cross-region pull.
    """
    now = time.monotonic()
    cached = _cred_cache.get(region)
    if cached and cached[2] > now:
        return cached[0], cached[1]

    try:
        resp = client("ecr", region=region).get_authorization_token()
        token_b64 = resp["authorizationData"][0]["authorizationToken"]
        user, password = base64.b64decode(token_b64).decode().split(":", 1)
    except Exception as exc:
        raise RuntimeError(f"could not mint ECR credentials: {exc}") from exc

    _cred_cache[region] = (user, password, now + _TOKEN_TTL_SECONDS - _TOKEN_REFRESH_MARGIN_SECONDS)
    return user, password
