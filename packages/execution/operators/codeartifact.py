"""CodeArtifact token minting for pip installs in the Airflow worker.

This is worker-runtime code, not shared foundation logic: it runs *only* in the
Airflow worker container (which carries the IAM role / web-identity credentials),
needs ``boto3``, and is called by :mod:`operators.tool_operator` at pip-install
time. It deliberately lives in ``worker`` rather than ``core`` — ``core`` is the
foundation library imported by every backend service and must not depend on
boto3 or AWS runtime access. The shared *URL-shape* contract
(``rewrite_url_for_tool_container`` / ``resolve_package_index_url``) stays in
``core.packaging``; the act of minting a token against AWS lives here.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse, urlunparse

import boto3

logger = logging.getLogger(__name__)


def _get_codeartifact_token() -> str | None:
    """Mint a fresh CodeArtifact authorization token.

    Runs only in the Airflow worker container (has IAM role / web-identity
    credentials attached). Returns a short-lived token, or ``None`` on error so
    the caller can fall back to the URL without auth rather than crash.

    Called at pip-install time (not at service startup), so it always gets a
    fresh token — this is what lets the platform avoid Secrets Manager / Lambda
    rotation entirely.
    """
    try:
        client = boto3.client(
            "codeartifact", region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        domain = os.getenv("CODEARTIFACT_DOMAIN", "techneos")
        # The Airflow services set CODEARTIFACT_DOMAIN_OWNER; fall back to the
        # generic AWS_ACCOUNT_ID for environments that only export that.
        domain_owner = os.getenv("CODEARTIFACT_DOMAIN_OWNER") or os.getenv(
            "AWS_ACCOUNT_ID"
        )

        if not domain_owner:
            logger.warning(
                "CODEARTIFACT_DOMAIN_OWNER / AWS_ACCOUNT_ID not set — "
                "cannot mint CodeArtifact token"
            )
            return None

        response = client.get_authorization_token(
            domain=domain,
            domainOwner=domain_owner,
            durationSeconds=3600,  # 1 hour (shorter than the default 12h)
        )
        return response.get("authorizationToken")
    except Exception as e:
        logger.warning("Failed to mint CodeArtifact token: %s", e)
        return None


def _inject_token_into_url(url: str, token: str) -> str:
    """Inject a CodeArtifact token into a URL (replaces any existing credentials)."""
    parsed = urlparse(url)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    # Inject token as username, no password.
    new_netloc = f"aws:{token}@{netloc}"
    return urlunparse(parsed._replace(netloc=new_netloc))


def _should_mint_token(url: str | None) -> bool:
    """Check if URL is a CodeArtifact endpoint that needs token minting."""
    if not url:
        return False
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    # CodeArtifact endpoints look like *.d.codeartifact.<region>.amazonaws.com
    return ".d.codeartifact." in hostname and "amazonaws.com" in hostname


def mint_codeartifact_token_for_url(url: str | None) -> str | None:
    """Mint a fresh CodeArtifact token and inject it into a URL if needed.

    Called by the Airflow worker at pip-install time. For CodeArtifact URLs a
    fresh token is minted and injected; for local PyPI (devpi/pypiserver) the URL
    is returned unchanged. Returns ``None`` if the input URL is ``None``.
    """
    if not url:
        return None

    if not _should_mint_token(url):
        # Local PyPI or other non-CodeArtifact URL — use as-is.
        return url

    token = _get_codeartifact_token()
    if not token:
        logger.warning("Failed to mint CodeArtifact token — pip may fail with 403")
        # Return the URL unchanged; pip will fail with 403, which is a clearer
        # signal than crashing the task here.
        return url

    return _inject_token_into_url(url, token)
