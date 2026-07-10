"""Environment resolution for management scripts.

The target gateway/portal URLs come from environment variables —
``PLATFORM_API_URL`` / ``PLATFORM_PORTAL_URL`` — set per environment in the
``.env.<env>`` that gets sourced (CodeArtifact/devpi for prod/dev). They default
to the local stack, so a bare local run needs no config.

``--env`` only canonicalises the environment name (``local`` -> ``development``,
``prod`` -> ``production``); that name selects the token-cache file
(``~/.techneos/<env>_token.json``) and which ``.env.<env>`` the wrappers auto-load.

Usage::

    from management.environment import resolve_environment

    env = resolve_environment("production")
    print(f"Targeting {env.name} at {env.api_url}")
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Environment:
    name: str
    api_url: str
    portal_url: str = ""

    def __str__(self) -> str:
        return f"{self.name} ({self.api_url})"


ENVIRONMENT_ALIASES: dict[str, str] = {
    "local": "development",
    "prod": "production",
}


def _canonical_env(name: str) -> str:
    return ENVIRONMENT_ALIASES.get(name, name)


def resolve_environment(env_arg: str | None = None) -> Environment:
    """Resolve the target environment's gateway + portal URLs.

    URLs come from ``PLATFORM_API_URL`` / ``PLATFORM_PORTAL_URL`` (set in the
    sourced ``.env.<env>``), defaulting to the local stack. ``env_arg`` only
    canonicalises the name used for the token-cache file.
    """
    canonical = _canonical_env(env_arg or "development")
    api_url = os.environ.get("PLATFORM_API_URL", "http://localhost:8000")
    portal_url = os.environ.get("PLATFORM_PORTAL_URL", "http://localhost:3000")
    return Environment(
        name=canonical,
        api_url=api_url.rstrip("/"),
        portal_url=portal_url.rstrip("/"),
    )
