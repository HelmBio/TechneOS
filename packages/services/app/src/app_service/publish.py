"""Package-index publishing + read credentials for the artifact publisher.

app-service is the platform's single artifact publisher (wheels *and* images), so
the wheel-publish path and the ``/simple/`` read proxy live here. The AWS
specifics (CodeArtifact tokens) come from the shared :mod:`techneos_aws`
package; this module only wires the platform settings to them and shells out to
``uv publish``.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from techneos_aws import codeartifact

from core.config import get_settings

logger = logging.getLogger(__name__)


def publish_wheel_to_index(wheel_path: Path) -> str:
    """Publish a wheel to the package index using uv.

    For CodeArtifact, mints a fresh token before publishing. Returns the publish
    URL on success. Raises RuntimeError on failure.
    """
    settings = get_settings()
    publish_url, username, password = _resolve_publish_credentials(settings)

    logger.info("Publishing %s to %s", wheel_path.name, publish_url)
    env = os.environ.copy()
    env["UV_PUBLISH_URL"] = publish_url
    env["UV_PUBLISH_USERNAME"] = username
    env["UV_PUBLISH_PASSWORD"] = password

    result = subprocess.run(
        ["uv", "publish", str(wheel_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        if "already exists" in result.stderr:
            logger.info("Wheel version already exists, skipping publish.")
            return publish_url
        raise RuntimeError(f"uv publish failed: {result.stderr}")

    logger.info("Published %s", wheel_path.name)
    return publish_url


def _resolve_publish_credentials(settings) -> tuple[str, str, str]:
    """Resolve (publish_url, username, password) for uv publish.

    For CodeArtifact: mints a fresh token (username "aws"). For devpi: uses
    configured credentials.
    """
    publish_url = settings.package_index_publish_url
    if not publish_url:
        raise RuntimeError(
            "No publish URL configured. Set PYTHON_PACKAGE_PUBLISH_URL "
            "in the environment."
        )

    if codeartifact.is_codeartifact_url(publish_url):
        token = codeartifact.mint_token(
            settings.codeartifact_domain,
            settings.codeartifact_domain_owner,
            settings.codeartifact_repository,
        )
        if not token:
            raise RuntimeError(
                "Could not mint CodeArtifact token. Check AWS credentials "
                "and CODEARTIFACT_DOMAIN / CODEARTIFACT_DOMAIN_OWNER settings."
            )
        return publish_url, "aws", token

    username = settings.package_index_user or "devpi"
    password = settings.package_index_password or "devpi"
    return publish_url, username, password


def resolve_index_read_credentials(settings) -> tuple[str, str] | None:
    """Resolve (username, password) for reading from the package index.

    Mirrors _resolve_publish_credentials, but for the read/proxy side and keyed
    off package_index_url (what /simple/* proxies to). For CodeArtifact it mints
    a fresh token (username "aws"); for devpi it returns the static configured
    credentials. Returns None when no credentials apply (anonymous index).

    Raises RuntimeError if a CodeArtifact token can't be minted — an
    unauthenticated read there is guaranteed to 401.
    """
    index_url = settings.package_index_url
    if index_url and codeartifact.is_codeartifact_url(index_url):
        token = codeartifact.mint_token(
            settings.codeartifact_domain,
            settings.codeartifact_domain_owner,
            settings.codeartifact_repository,
        )
        if not token:
            raise RuntimeError(
                "Could not mint CodeArtifact token for index reads. Check AWS "
                "credentials and CODEARTIFACT_DOMAIN / CODEARTIFACT_DOMAIN_OWNER."
            )
        return "aws", token

    user = settings.package_index_user
    password = settings.package_index_password
    if user and password:
        return user, password
    return None


def index_is_codeartifact(settings) -> bool:
    """True when the read index (package_index_url) is a CodeArtifact endpoint."""
    return bool(settings.package_index_url) and codeartifact.is_codeartifact_url(
        settings.package_index_url
    )


def list_codeartifact_packages(settings) -> list[str]:
    """List every pypi package name in the CodeArtifact repo.

    Used to synthesize a PEP 503 root index (CodeArtifact serves none). Raises
    RuntimeError on incomplete config.
    """
    return codeartifact.list_packages(
        settings.codeartifact_domain,
        settings.codeartifact_domain_owner,
        settings.codeartifact_repository,
    )
