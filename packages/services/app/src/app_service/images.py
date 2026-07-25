"""Image publishing for the whole platform — apps *and* container tools.

app-service owns image publishing because it is the service with docker-daemon
access (the mounted ``/var/run/docker.sock``). The gateway is deliberately kept
off the socket as the internet-facing component, so it proxies
``POST /api/v1/artifacts/image`` here instead of pushing itself. Container-tool
and app registrations both land on this one path.

Uses the docker SDK (same client app-service already uses to deploy apps), so no
docker CLI binary is required in the image. ECR auth/repository management lives
in the shared :mod:`aws.ecr` package. For a registry push (prod ECR) the image
is loaded into the daemon and pushed with a freshly-minted ECR token; with no
registry configured (local dev) it is only loaded + tagged locally so a local
worker can run it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import docker
from techneos_aws import ecr

from core.config import get_settings

logger = logging.getLogger(__name__)


def publish_image_to_registry(tar_path: Path, slug: str, version: str) -> str:
    """Load an image tar into the daemon and push it to the registry.

    Returns the full image reference (``{registry}/techneos/<slug>:<version>``,
    or the bare ``techneos/<slug>:<version>`` in local dev). Raises RuntimeError
    on any failure — the route maps that to a 502 with the message.
    """
    settings = get_settings()
    registry = settings.docker_image_registry
    image = f"techneos/{slug}"

    try:
        client = docker.from_env()
    except docker.errors.DockerException as exc:
        raise RuntimeError(f"cannot reach the docker daemon: {exc}") from exc

    logger.info("Loading image from %s", tar_path.name)
    try:
        with open(tar_path, "rb") as fh:
            client.images.load(fh.read())
        local = client.images.get(f"{image}:{version}")
    except Exception as exc:
        raise RuntimeError(f"docker load failed for {tar_path.name}: {exc}") from exc

    if not registry:
        # Local dev, no registry: tag :latest locally so a local worker can run
        # the image. (The daemon is the local one via the mounted socket.)
        try:
            local.tag(image, tag="latest")
        except Exception as exc:
            raise RuntimeError(f"docker tag failed for {image}:latest: {exc}") from exc
        logger.info("Loaded %s:%s (local, no registry)", image, version)
        return f"{image}:{version}"

    ecr_repo = f"{registry}/{image}"
    auth_config: dict[str, str] | None = None
    if ecr.is_ecr_registry(registry):
        # ECR: the repository must exist before the first push, and the daemon
        # needs the registry's short-lived token.
        ecr.ensure_repository(image)
        user, password = ecr.mint_credentials()
        auth_config = {"username": user, "password": password}

    for tag in (version, "latest"):
        try:
            local.tag(ecr_repo, tag=tag)
        except Exception as exc:
            raise RuntimeError(f"docker tag failed for {ecr_repo}:{tag}: {exc}") from exc
        logger.info("Pushing %s:%s", ecr_repo, tag)
        _push(client, ecr_repo, tag, auth_config)

    logger.info("Pushed %s:%s", ecr_repo, version)
    return f"{ecr_repo}:{version}"


def _push(client: docker.DockerClient, repo: str, tag: str, auth_config: dict | None) -> None:
    """Push one tag, raising RuntimeError on failure.

    ``images.push`` does not raise on a failed push — errors are reported inline
    in the streamed status objects, so scan them for an ``error`` key.
    """
    errors: list[str] = []
    for line in client.images.push(repo, tag=tag, auth_config=auth_config, stream=True, decode=True):
        if "error" in line:
            errors.append(str(line.get("error")))
    if errors:
        raise RuntimeError(f"push to {repo}:{tag} failed: {'; '.join(errors)}")
