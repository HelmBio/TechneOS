"""Resolution of the Python package index URL for installing pypi-type tools.

Shared by the tool-service and pipeline-service orchestrators so a pypi tool
installs from the same index regardless of whether it runs as a direct
tool-run or as a step inside a pipeline.

This module holds the *URL-shape contract* only. For CodeArtifact URLs the index
URL is returned without credentials; a fresh token is minted at pip-install time
by the Airflow worker (``operators.codeartifact.mint_codeartifact_token_for_url``),
which keeps the boto3/IAM dependency out of ``core`` (the foundation library
imported by every service).
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from core.config import get_settings


def rewrite_url_for_tool_container(url: str | None) -> str | None:
    """Translate a host-side URL into one a Docker container can resolve.

    The only rewrite we perform is ``localhost`` / ``127.0.0.1`` →
    ``host.docker.internal``. That captures the dev-machine case where
    the platform services run on the host and reach pypiserver via a
    host-mapped port, but a spawned tool container needs to reach the
    same pypiserver through Docker Desktop's host alias.

    Other hostnames — in-compose service names, prod CodeArtifact, a
    private partner registry — are left alone.
    """
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        return url
    new_netloc = "host.docker.internal"
    if parsed.port is not None:
        new_netloc = f"{new_netloc}:{parsed.port}"
    if parsed.username or parsed.password:
        creds = parsed.username or ""
        if parsed.password is not None:
            creds = f"{creds}:{parsed.password}"
        new_netloc = f"{creds}@{new_netloc}"
    return urlunparse(parsed._replace(netloc=new_netloc))


def resolve_package_index_url(per_tool_url: str | None) -> str | None:
    """Resolve the effective pip ``--index-url`` for a pypi tool install.

    Resolution order: per-tool override → the platform's configured
    ``package_index_url`` (``core.config.Settings``, sourced from
    ``PYTHON_PACKAGE_INDEX_URL`` in env / ``.env``). The per-tool URL is for
    exceptional cases (a tool that genuinely ships from a different index);
    platform defaults flow from settings so dev (devpi/pypiserver) vs prod
    (CodeArtifact) lives in env files, not in the DB. The result is rewritten
    so a spawned tool container can reach a host-mapped index (see
    :func:`rewrite_url_for_tool_container`).

    Reading from ``Settings`` (not raw ``os.environ``) matters: services are
    launched without exporting ``.env`` into the process environment, so only
    the pydantic settings loader sees the configured value.

    **Token minting is deferred to the worker** — CodeArtifact URLs are returned
    as-is (without embedded credentials). The worker calls
    ``operators.codeartifact.mint_codeartifact_token_for_url()`` at pip-install
    time to inject a fresh token if needed.

    Returns ``None`` when neither a per-tool URL nor a configured index is
    set, in which case the worker installs from the default index (PyPI).
    """
    resolved = (per_tool_url or get_settings().package_index_url) or None
    return rewrite_url_for_tool_container(resolved)
