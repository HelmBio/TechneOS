#!/usr/bin/env python3
"""Register the Platform Assistant with the TechneOS platform.

Creates two resources if they don't already exist:
  1. The default LLM provider (TechneOS Gemini) — admin API
  2. The Platform Assistant AgentDefinition (is_platform=True) — agents API

Idempotent: both operations check for existing resources by slug.
Pass ``--upsert`` to recreate the agent definition even if it already exists.

Usage:
  uv run python packages/platform-assistant/build_and_register.py                        # default: --env=local
  uv run python packages/platform-assistant/build_and_register.py --env=local
  uv run python packages/platform-assistant/build_and_register.py --env=prod
  uv run python packages/platform-assistant/build_and_register.py --env=prod --upsert
  uv run python packages/platform-assistant/build_and_register.py --email admin@example.com --password pw

Authentication (all envs):
  1. Reuses a valid cached token from ``~/.techneos/{env}_token.json`` if present.
  2. Otherwise, prompts for admin email + password and mints a JWT via ``POST /api/v1/auth/login``.
  3. Pass ``--email`` / ``--password`` to skip interactive prompts (e.g. for scripting).
"""

from __future__ import annotations

import argparse
import sys

import httpx
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
from platform_assistant.config import default_platform_assistant_config

LLM_PROVIDER_PAYLOAD = {
    "name": "TechneOS Gemini",
    "slug": "techneos-gemini",
    "provider_type": "openai_compatible",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "default_model": "gemini-2.5-pro",
    "supported_models": ["gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite"],
    "max_tokens": 8192,
    "is_default": True,
}

AGENT_SLUG = "platform-assistant"
LLM_PROVIDER_SLUG = "techneos-gemini"


def _ensure_llm_provider(api_url: str, headers: dict, org_id: str) -> str:
    """Create the default LLM provider if it doesn't exist. Returns its id."""
    existing = find_resource_by_slug(
        api_url, headers, "/api/v1/admin/llm-providers?skip=0&limit=100", LLM_PROVIDER_SLUG
    )
    if existing is not None:
        print(f"  LLM provider already exists: {existing}")
        return existing

    print("  Not found — creating ...")
    print("  Warning: no API key env var configured. Provider will be created without an API key.")
    print("  Set the key later via the admin UI.")

    payload = {**LLM_PROVIDER_PAYLOAD, "api_key": None, "org_id": org_id}
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


def _ensure_agent(api_url: str, headers: dict, org_id: str, upsert: bool) -> str:
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
    provider_slug = defaults["provider_slug"]
    model_name = defaults["model_name"]
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
        "model_config": {
            "provider": provider_slug,
            "model": model_name,
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

    token = authenticate(api_url, args.email, args.password)
    headers = auth_headers(token)

    print("=== Resolving org_id ===")
    org_id = resolve_org_id(api_url, headers)
    print(f"  org_id: {org_id}")
    print()

    print(f"=== LLM Provider: {LLM_PROVIDER_SLUG} ===")
    _ensure_llm_provider(api_url, headers, org_id)
    print()

    print(f"=== Platform Assistant AgentDefinition: {AGENT_SLUG} ===")
    _ensure_agent(api_url, headers, org_id, args.upsert)
    print()

    print("=== Registration complete ===")
    print(f"  LLM Provider:   {LLM_PROVIDER_SLUG}")
    print(f"  Platform Agent: {AGENT_SLUG}")


if __name__ == "__main__":
    main()
