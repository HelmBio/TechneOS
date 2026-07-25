"""CodeArtifact primitives — auth tokens, package listing, URL detection.

Pure boto3 helpers, decoupled from platform settings: callers pass the
domain/owner/repository they read from their own config. The artifact publisher
(wheel publish) and the index read-proxy use these; no service embeds
``get_authorization_token`` itself.
"""

from __future__ import annotations

import logging
import time

from techneos_aws.credentials import client

logger = logging.getLogger(__name__)

# CodeArtifact tokens are valid up to 12h; we mint for 1h and cache per
# (domain, owner) so the read proxy — hit repeatedly while uv/pip resolve a
# dependency tree — doesn't call get_authorization_token on every request.
# Refreshed a few minutes early so an in-flight request never uses a token that
# expires mid-flight.
_TOKEN_TTL_SECONDS = 3600
_TOKEN_REFRESH_MARGIN_SECONDS = 300
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


def is_codeartifact_url(url: str) -> bool:
    """True if ``url`` is a CodeArtifact endpoint."""
    return "codeartifact" in url.lower()


def mint_token(domain: str, domain_owner: str, repository: str | None = None) -> str | None:
    """Mint a CodeArtifact auth token (username is always ``aws``), cached per
    (domain, owner).

    The token is domain-scoped, so only ``domain`` + ``domain_owner`` are
    required; ``repository`` is accepted for callers that carry it but is not
    needed to mint. Returns ``None`` when coordinates are incomplete or the call
    fails — the caller decides whether that is fatal.
    """
    if not all([domain, domain_owner]):
        logger.warning(
            "CodeArtifact coordinates incomplete (domain=%s, owner=%s)",
            domain, domain_owner,
        )
        return None

    cache_key = (domain, domain_owner)
    now = time.monotonic()
    cached = _token_cache.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    try:
        resp = client("codeartifact").get_authorization_token(
            domain=domain, domainOwner=domain_owner, durationSeconds=_TOKEN_TTL_SECONDS,
        )
        token = resp["authorizationToken"]
    except Exception as exc:
        logger.error("Failed to mint CodeArtifact token: %s", exc)
        return None

    _token_cache[cache_key] = (token, now + _TOKEN_TTL_SECONDS - _TOKEN_REFRESH_MARGIN_SECONDS)
    return token


def list_packages(domain: str, domain_owner: str, repository: str) -> list[str]:
    """List every pypi package name in the CodeArtifact repo (control-plane API).

    CodeArtifact serves no PEP 503 root listing, so this is the only way to
    enumerate packages for a synthesized root index. Names are returned as
    stored; the caller normalizes them for PEP 503 hrefs. Raises RuntimeError on
    incomplete coordinates.
    """
    if not all([domain, domain_owner, repository]):
        raise RuntimeError(
            "CodeArtifact coordinates incomplete — set CODEARTIFACT_DOMAIN / "
            "CODEARTIFACT_DOMAIN_OWNER / CODEARTIFACT_REPOSITORY."
        )

    names: list[str] = []
    paginator = client("codeartifact").get_paginator("list_packages")
    for page in paginator.paginate(
        domain=domain, domainOwner=domain_owner, repository=repository, format="pypi"
    ):
        for pkg in page.get("packages", []):
            name = pkg.get("package")
            if name:
                names.append(name)
    return names
