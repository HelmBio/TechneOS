#!/usr/bin/env python3
"""Register the Platform Assistant with the TechneOS platform.

Creates two resources if they don't already exist:
  1. The default LLM provider — admin API
  2. The Platform Assistant AgentDefinition (is_platform=True) — agents API

The provider fields come from ``setup/database/.techneos.<env>.json``; the API
key (a secret) and any overrides come from ``DEFAULT_LLM_*`` in ``.env``.
Registration is skipped entirely if the required provider info (including the
API key) is missing — a keyless provider can't serve the assistant.

Idempotent: both operations check for existing resources by slug.
Pass ``--upsert`` to recreate the agent definition even if it already exists.

Usage:
  python setup/register_platform_assistant.py                        # default: --env=local
  python setup/register_platform_assistant.py --env=prod
  python setup/register_platform_assistant.py --env=prod --upsert
  python setup/register_platform_assistant.py --email admin@example.com --password pw

Authentication (all envs):
  1. Reuses a valid cached token from ``~/.techneos/{env}_token.json`` if present.
  2. Otherwise, prompts for admin email + password and mints a JWT via ``POST /api/v1/auth/login``.
  3. Pass ``--email`` / ``--password`` to skip interactive prompts (e.g. for scripting).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from platform_assistant.config import default_platform_assistant_config
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.config import get_settings
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    auth_headers,
    authenticate,
    find_resource_by_slug,
    resolve_api_url,
    resolve_org_id,
)

AGENT_SLUG = "platform-assistant"

# Provider fields required to register a usable LLM provider. The api_key comes
# only from the environment (it's a secret); the rest default from the JSON.
_REQUIRED_LLM_FIELDS = ("name", "slug", "provider_type", "base_url", "default_model", "api_key")

# DEFAULT_LLM_* env var (via the field name below) -> llm_provider config key.
_LLM_OVERRIDE_MAP = {
    "default_llm_name": "name",
    "default_llm_slug": "slug",
    "default_llm_provider_type": "provider_type",
    "default_llm_base_url": "base_url",
    "default_llm_default_model": "default_model",
    "default_llm_max_tokens": "max_tokens",
    "default_llm_api_key": "api_key",
}


class LLMProviderOverrides(BaseSettings):
    """``DEFAULT_LLM_*`` overrides for the seeded LLM provider, read from ``.env``.

    The API key has no JSON default — it is supplied only here, so nothing
    secret lives in a committed file.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    default_llm_name: str | None = None
    default_llm_slug: str | None = None
    default_llm_provider_type: str | None = None
    default_llm_base_url: str | None = None
    default_llm_default_model: str | None = None
    default_llm_max_tokens: int | None = None
    default_llm_api_key: str | None = None


def load_llm_provider_config() -> dict[str, Any]:
    """Load the ``llm_provider`` block from the seed JSON, with ``.env`` overrides."""
    seed_dir = Path(__file__).resolve().parent / "database"
    candidates = [
        seed_dir / f".techneos.{get_settings().environment}.json",
        seed_dir / ".techneos.example.json",
    ]
    config: dict[str, Any] = {}
    for path in candidates:
        if path.exists():
            with open(path) as f:
                config = json.load(f).get("llm_provider", {})
            break

    overrides = LLMProviderOverrides()
    for attr, key in _LLM_OVERRIDE_MAP.items():
        value = getattr(overrides, attr)
        if value is not None:
            config[key] = value
    return config


def missing_llm_fields(config: dict[str, Any]) -> list[str]:
    """Return the required provider fields that are absent or empty."""
    return [field for field in _REQUIRED_LLM_FIELDS if not config.get(field)]


def _ensure_llm_provider(api_url: str, headers: dict, org_id: str, config: dict[str, Any]) -> str:
    """Create the default LLM provider if it doesn't exist. Returns its id."""
    slug = config["slug"]
    existing = find_resource_by_slug(
        api_url, headers, "/api/v1/admin/llm-providers?skip=0&limit=100", slug
    )
    if existing is not None:
        print(f"  LLM provider already exists: {existing}")
        return existing

    print("  Not found — creating ...")
    payload = {
        "name": config["name"],
        "slug": slug,
        "provider_type": config["provider_type"],
        "base_url": config["base_url"],
        "default_model": config["default_model"],
        "supported_models": config.get("supported_models", []),
        "max_tokens": config.get("max_tokens"),
        "is_default": config.get("is_default", True),
        "api_key": config["api_key"],
        "org_id": org_id,
    }
    resp = httpx.post(f"{api_url}/api/v1/admin/llm-providers", json=payload, headers=headers)
    if not resp.is_success:
        print(
            f"Error: failed to create LLM provider (HTTP {resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    provider_id = resp.json()["id"]
    print(f"  Created LLM provider: {provider_id}")
    return provider_id


def _ensure_agent(
    api_url: str, headers: dict, org_id: str, upsert: bool, provider: dict[str, Any]
) -> str:
    """Create or skip the Platform Assistant AgentDefinition. Returns its id."""
    existing = find_resource_by_slug(
        api_url, headers, "/api/v1/agents?include_platform=true&limit=100", AGENT_SLUG
    )

    if existing is not None and not upsert:
        print(f"  Platform Assistant already exists: {existing} (use --upsert to recreate)")
        return existing

    if existing is not None and upsert:
        print(f"  Recreating (--upsert) — deleting {existing} ...")
        resp = httpx.delete(f"{api_url}/api/v1/agents/{existing}", headers=headers)
        if not resp.is_success:
            print(
                f"Error: failed to delete existing agent (HTTP {resp.status_code})", file=sys.stderr
            )
            sys.exit(1)
        print("  Deleted. Proceeding to create ...")

    if existing is None:
        print("  Not found — creating ...")

    defaults = default_platform_assistant_config()
    prompt = defaults["system_prompt"]
    tools = defaults["tools"]
    max_tokens = defaults.get("max_tokens")
    temperature = defaults.get("temperature")

    payload = {
        "name": "Platform Assistant",
        "slug": AGENT_SLUG,
        "description": "Built-in platform assistant — ask about datasets, tools, pipelines, and agents",
        "agent_type": "conversational",
        "framework": "custom",
        "is_platform": True,
        "is_public": True,
        "system_prompt": prompt,
        # Point the assistant at the provider we just registered, so the two
        # stay in sync even when the provider slug/model are overridden in .env.
        "model_config": {
            "provider": provider["slug"],
            "model": provider["default_model"],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        "tools": tools,
    }

    resp = httpx.post(f"{api_url}/api/v1/agents", json=payload, headers=headers)
    if not resp.is_success:
        print(
            f"Error: failed to create Platform Assistant (HTTP {resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    agent_id = resp.json()["id"]
    print(f"  Created Platform Assistant: {agent_id}")
    return agent_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the Platform Assistant with the TechneOS platform.",
    )
    add_env_arg(parser)
    add_upsert_arg(parser)
    add_auth_args(parser)
    args = parser.parse_args()

    api_url = resolve_api_url(args.env)
    print(f"=== Target environment: {args.env} ===")
    print(f"  API URL:  {api_url}")
    print()

    provider = load_llm_provider_config()
    missing = missing_llm_fields(provider)
    if missing:
        print("=== Skipping Platform Assistant registration ===")
        print(f"  Missing required LLM provider info: {', '.join(missing)}")
        print("  Set DEFAULT_LLM_API_KEY (and any other DEFAULT_LLM_* overrides) in .env,")
        print("  then re-run. A provider without an API key can't serve the assistant.")
        return

    # The platform encrypts the API key at rest, which needs SECRETS_ENCRYPTION_KEY;
    # without it the create call fails server-side, so skip with an actionable hint.
    if not get_settings().secrets_encryption_key:
        print("=== Skipping Platform Assistant registration ===")
        print("  DEFAULT_LLM_API_KEY is set, but SECRETS_ENCRYPTION_KEY is not configured —")
        print("  the platform needs it to store the API key at rest. Generate one with:")
        print('    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
        print("  add it to .env as SECRETS_ENCRYPTION_KEY, restart the auth service, then re-run.")
        return

    token = authenticate(api_url, args.email, args.password)
    headers = auth_headers(token)

    print("=== Resolving org_id ===")
    org_id = resolve_org_id(api_url, headers)
    print(f"  org_id: {org_id}")
    print()

    print(f"=== LLM Provider: {provider['slug']} ===")
    _ensure_llm_provider(api_url, headers, org_id, provider)
    print()

    print(f"=== Platform Assistant AgentDefinition: {AGENT_SLUG} ===")
    _ensure_agent(api_url, headers, org_id, args.upsert, provider)
    print()

    print("=== Registration complete ===")
    print(f"  LLM Provider:   {provider['slug']}")
    print(f"  Platform Agent: {AGENT_SLUG}")


if __name__ == "__main__":
    main()
