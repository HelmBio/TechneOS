#!/usr/bin/env python3
"""Register the Platform Assistant with the TechneOS platform.

A gateway operation: it authenticates as a platform admin and talks to the
REST API only (no direct DB access). The default LLM provider it needs is
seeded separately, straight to the DB, by ``migrations/seed/seed.py`` (run via
``make seed``). This script discovers that provider and registers the built-in
Platform Assistant AgentDefinition (``is_platform=True``) against it.

If no LLM provider exists yet, registration is skipped with a hint to seed one
— a provider is what makes the assistant able to answer, so there's nothing to
register without it.

Idempotent: the agent is matched by slug. Pass ``--upsert`` to recreate the
agent definition even if it already exists.

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
import sys
from typing import Any

import httpx
from platform_assistant.config import default_platform_assistant_config

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


def _find_default_provider(api_url: str, headers: dict, org_id: str) -> dict[str, Any] | None:
    """Return the org's default (else first active) LLM provider, or ``None``.

    The provider is seeded straight to the DB by ``make seed``; here we just
    read it back through the API to point the assistant at it.
    """
    resp = httpx.get(
        f"{api_url}/api/v1/orgs/{org_id}/llm-providers?limit=100", headers=headers
    )
    if not resp.is_success:
        print(
            f"Error: failed to list LLM providers (HTTP {resp.status_code}): {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    providers = [p for p in resp.json().get("items", []) if p.get("is_active", True)]
    if not providers:
        return None
    # Prefer the one flagged default; otherwise the first active provider.
    return next((p for p in providers if p.get("is_default")), providers[0])


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
        # Point the assistant at the seeded default provider, by slug + model.
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

    token = authenticate(api_url, args.env, args.email, args.password)
    headers = auth_headers(token)

    print("=== Resolving org_id ===")
    org_id = resolve_org_id(api_url, headers)
    print(f"  org_id: {org_id}")
    print()

    print("=== Locating the default LLM provider ===")
    provider = _find_default_provider(api_url, headers, org_id)
    if provider is None:
        print("=== Skipping Platform Assistant registration ===")
        print("  No LLM provider found for this org. Seed one first:")
        print("    set DEFAULT_LLM_API_KEY (and SECRETS_ENCRYPTION_KEY) in .env, then `make seed`.")
        print("  A provider is what lets the assistant answer, so there's nothing to register yet.")
        return
    print(f"  Using provider: {provider['slug']} (model: {provider['default_model']})")
    print()

    print(f"=== Platform Assistant AgentDefinition: {AGENT_SLUG} ===")
    _ensure_agent(api_url, headers, org_id, args.upsert, provider)
    print()

    print("=== Registration complete ===")
    print(f"  LLM Provider:   {provider['slug']}")
    print(f"  Platform Agent: {AGENT_SLUG}")


if __name__ == "__main__":
    main()
