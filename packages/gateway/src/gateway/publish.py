"""Publishing utilities for the gateway.

Handles publishing wheels to the package index and pushing docker images
to the registry. The gateway owns the credentials — catalog clients never
connect directly to the index or registry.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import boto3

from core.config import get_settings

logger = logging.getLogger(__name__)

# CodeArtifact tokens are valid for up to 12h; we mint them for 1h and cache
# per (domain, owner) so the read proxy — hit repeatedly by uv/pip resolving a
# dependency tree — doesn't call get_authorization_token on every request.
# Refreshed a few minutes early so an in-flight request never uses a token that
# expires mid-flight.
_TOKEN_TTL_SECONDS = 3600
_TOKEN_REFRESH_MARGIN_SECONDS = 300
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


def publish_wheel_to_index(wheel_path: Path) -> str:
    """Publish a wheel to the package index using uv.

    Uses gateway credentials from settings. For CodeArtifact, mints a fresh
    token before publishing. Returns the publish URL on success.

    Raises RuntimeError on failure.
    """
    settings = get_settings()
    publish_url, username, password = _resolve_publish_credentials(settings)

    print(f"  Publishing {wheel_path.name} to {publish_url} ...")
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
            print("  Wheel version already exists, skipping publish.")
            return publish_url
        raise RuntimeError(f"uv publish failed: {result.stderr}")

    print(f"  Published {wheel_path.name}")
    return publish_url


def push_image_to_registry(
    tar_path: Path,
    slug: str,
    version: str,
) -> str:
    """Push a docker image to the registry.

    Loads the image from the tar file, tags it for the registry, and pushes.
    For local dev (no registry configured), just loads into local daemon.

    Returns the full image reference (e.g., ``{registry}/{slug}:{version}``).
    Raises RuntimeError on failure.
    """
    settings = get_settings()
    registry = settings.docker_image_registry
    image = f"techneos/{slug}"

    # Load image from tar
    print(f"  Loading image from {tar_path.name} ...")
    _run_docker(
        ["docker", "load", "-i", str(tar_path)],
        errmsg=f"docker load failed for {tar_path.name}",
    )

    if registry:
        # Tag and push to registry
        ecr_image = f"{registry}/{image}"
        _run_docker(
            ["docker", "tag", f"{image}:{version}", f"{ecr_image}:{version}"],
            errmsg=f"docker tag failed for {ecr_image}:{version}",
        )
        _run_docker(
            ["docker", "tag", f"{image}:{version}", f"{ecr_image}:latest"],
            errmsg=f"docker tag failed for {ecr_image}:latest",
        )
        print(f"  Pushing {ecr_image}:{version} ...")
        _run_docker(
            ["docker", "push", f"{ecr_image}:{version}"],
            errmsg=f"docker push failed for {ecr_image}:{version}",
        )
        _run_docker(
            ["docker", "push", f"{ecr_image}:latest"],
            errmsg=f"docker push failed for {ecr_image}:latest",
        )
        print(f"  Pushed {ecr_image}:{version}")
        return f"{ecr_image}:{version}"
    else:
        # Local dev — just tag locally
        _run_docker(
            ["docker", "tag", f"{image}:{version}", f"{image}:latest"],
            errmsg=f"docker tag failed for {image}:latest",
        )
        print(f"  Loaded {image}:{version} (local)")
        return f"{image}:{version}"


def _resolve_publish_credentials(settings) -> tuple[str, str, str]:
    """Resolve (publish_url, username, password) for uv publish.

    For CodeArtifact: mints a fresh token (username "aws").
    For devpi: uses configured credentials.
    """
    publish_url = settings.package_index_publish_url

    if not publish_url:
        raise RuntimeError(
            "No publish URL configured. Set PYTHON_PACKAGE_PUBLISH_URL "
            "in the environment."
        )

    # Check if this is a CodeArtifact URL
    if _is_codeartifact_url(publish_url):
        token = _mint_codeartifact_token(settings)
        if not token:
            raise RuntimeError(
                "Could not mint CodeArtifact token. Check AWS credentials "
                "and CODEARTIFACT_DOMAIN / CODEARTIFACT_DOMAIN_OWNER settings."
            )
        return publish_url, "aws", token

    # Use configured credentials (devpi)
    username = settings.package_index_user or "devpi"
    password = settings.package_index_password or "devpi"
    return publish_url, username, password


def resolve_index_read_credentials(settings) -> tuple[str, str] | None:
    """Resolve (username, password) for reading from the package index.

    Mirrors _resolve_publish_credentials, but for the read/proxy side and
    keyed off package_index_url (what /simple/* proxies to). For CodeArtifact
    it mints a fresh token (username "aws"); for devpi it returns the static
    configured credentials. Returns None when no credentials apply (an
    anonymous index), so the caller sends no Authorization header.

    Raises RuntimeError if a CodeArtifact token can't be minted — an
    unauthenticated read there is guaranteed to 401, so failing loudly beats
    silently proxying a doomed request.
    """
    index_url = settings.package_index_url

    if index_url and _is_codeartifact_url(index_url):
        token = _mint_codeartifact_token(settings)
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
    return bool(settings.package_index_url) and _is_codeartifact_url(settings.package_index_url)


def list_codeartifact_packages(settings) -> list[str]:
    """List every pypi package name in the CodeArtifact repo.

    Uses the control-plane API (list_packages), not the Simple endpoint —
    CodeArtifact does not serve a PEP 503 root listing, so this is the only way
    to enumerate packages for a synthesized root index. Names are returned as
    stored; the caller normalizes them for PEP 503 hrefs. Uses the instance IAM
    role directly (no token needed). Raises RuntimeError on incomplete config.
    """
    domain = settings.codeartifact_domain
    domain_owner = settings.codeartifact_domain_owner
    repository = settings.codeartifact_repository
    if not all([domain, domain_owner, repository]):
        raise RuntimeError(
            "CodeArtifact settings incomplete — set CODEARTIFACT_DOMAIN / "
            "CODEARTIFACT_DOMAIN_OWNER / CODEARTIFACT_REPOSITORY."
        )

    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("codeartifact", region_name=region)
    names: list[str] = []
    paginator = client.get_paginator("list_packages")
    for page in paginator.paginate(
        domain=domain, domainOwner=domain_owner, repository=repository, format="pypi"
    ):
        for pkg in page.get("packages", []):
            name = pkg.get("package")
            if name:
                names.append(name)
    return names


def _is_codeartifact_url(url: str) -> bool:
    """Check if a URL is a CodeArtifact endpoint."""
    return "codeartifact" in url.lower()


def _mint_codeartifact_token(settings) -> str | None:
    """Mint a CodeArtifact auth token via boto3, cached per (domain, owner)."""
    domain = settings.codeartifact_domain
    domain_owner = settings.codeartifact_domain_owner
    repository = settings.codeartifact_repository

    if not all([domain, domain_owner, repository]):
        logger.warning(
            "CodeArtifact settings incomplete (domain=%s, owner=%s, repo=%s)",
            domain, domain_owner, repository,
        )
        return None

    cache_key = (domain, domain_owner)
    now = time.monotonic()
    cached = _token_cache.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    try:
        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("codeartifact", region_name=region)
        response = client.get_authorization_token(
            domain=domain,
            domainOwner=domain_owner,
            durationSeconds=_TOKEN_TTL_SECONDS,
        )
        token = response["authorizationToken"]
        _token_cache[cache_key] = (
            token,
            now + _TOKEN_TTL_SECONDS - _TOKEN_REFRESH_MARGIN_SECONDS,
        )
        return token
    except Exception as exc:
        logger.error("Failed to mint CodeArtifact token: %s", exc)
        return None


def _run_docker(args: list[str], errmsg: str) -> None:
    """Run a docker command, raising RuntimeError on failure."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{errmsg}: {result.stderr}")
