"""Database seeding — default roles, org, team, admin user, and LLM provider.

A platform-admin operation, run once after the infrastructure and schema are
up (``make up`` + ``make migrate``) and before any catalog items are
registered. Not part of any shipped wheel and not imported by the services at
runtime — it writes directly to the database, which is why it lives alongside
the migrations rather than in ``setup/`` (whose scripts all go through the
gateway API).

Config is loaded from ``seed.defaults.json`` next to this file — one file for
every environment. The org, team, and admin-user values can be overridden per
deployment with ``DEFAULT_*`` variables in ``.env`` (see ``SeedOverrides``);
role definitions stay in the JSON, since their permission lists are too
structured for env vars and don't vary by environment anyway.

The default LLM provider that powers the Platform Assistant is seeded here too:
its fields default from the JSON ``llm_provider`` block, and its API key comes
only from ``DEFAULT_LLM_API_KEY`` (a secret, never committed). Without that key
the provider is skipped — a keyless provider can't serve the assistant — but
roles/org/team/admin still seed. ``register_platform_assistant`` (a gateway
operation in ``setup/``) then discovers this provider and registers the agent
against it.

    python migrations/seed/seed.py   # or: make seed
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, cast

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.providers import hash_password
from core.config import get_settings
from core.database.postgres import get_async_engine, get_session_factory
from core.models.llm_provider import LLMProvider
from core.models.user import Org, Role, Team, User
from core.security.fernet import encrypt_value


class SeedOverrides(BaseSettings):
    """Optional ``.env`` overrides for the seeded org, team, and admin user.

    Read from the same ``.env`` the platform uses. Each field maps to an
    uppercased environment variable (``default_org_slug`` ← ``DEFAULT_ORG_SLUG``);
    anything left unset falls back to the value in the JSON seed config. Keeping
    ``DEFAULT_ORG_SLUG`` here in sync with the auth service (which resolves a
    user's default org by the same variable) is what lets the seeded org and the
    runtime lookup agree.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    default_org_name: str | None = None
    default_org_slug: str | None = None
    default_team_name: str | None = None
    default_team_slug: str | None = None
    default_admin_email: str | None = None
    default_admin_password: str | None = None
    default_admin_full_name: str | None = None
    default_admin_role: str | None = None


# Each override attribute maps to a (section, key) in the JSON config.
_OVERRIDE_MAP: dict[str, tuple[str, str]] = {
    "default_org_name": ("org", "name"),
    "default_org_slug": ("org", "slug"),
    "default_team_name": ("team", "name"),
    "default_team_slug": ("team", "slug"),
    "default_admin_email": ("admin_user", "email"),
    "default_admin_password": ("admin_user", "password"),
    "default_admin_full_name": ("admin_user", "full_name"),
    "default_admin_role": ("admin_user", "role"),
}


class LLMProviderOverrides(BaseSettings):
    """``DEFAULT_LLM_*`` overrides for the seeded LLM provider, read from ``.env``.

    The API key has no JSON default — it is supplied only via
    ``DEFAULT_LLM_API_KEY``, so nothing secret lives in a committed file. When
    it is unset the provider is skipped entirely (see :func:`seed_llm_provider`).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    default_llm_name: str | None = None
    default_llm_slug: str | None = None
    default_llm_provider_type: str | None = None
    default_llm_base_url: str | None = None
    default_llm_default_model: str | None = None
    default_llm_max_tokens: int | None = None
    default_llm_api_key: str | None = None


# DEFAULT_LLM_* field name -> llm_provider JSON key.
_LLM_OVERRIDE_MAP: dict[str, str] = {
    "default_llm_name": "name",
    "default_llm_slug": "slug",
    "default_llm_provider_type": "provider_type",
    "default_llm_base_url": "base_url",
    "default_llm_default_model": "default_model",
    "default_llm_max_tokens": "max_tokens",
    "default_llm_api_key": "api_key",
}


def _llm_provider_config(config: dict[str, Any]) -> dict[str, Any]:
    """The JSON ``llm_provider`` block with ``DEFAULT_LLM_*`` env overrides applied.

    The API key comes only from ``DEFAULT_LLM_API_KEY`` (a secret, never in the
    committed JSON); everything else defaults from the JSON block.
    """
    provider = dict(config.get("llm_provider", {}))
    overrides = LLMProviderOverrides()
    for attr, key in _LLM_OVERRIDE_MAP.items():
        value = getattr(overrides, attr)
        if value is not None:
            provider[key] = value
    return provider


def _default_team_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "team"


def _apply_overrides(config: dict[str, Any], overrides: SeedOverrides) -> None:
    """Overlay any set ``DEFAULT_*`` env values onto the loaded config in place."""
    for attr, (section, key) in _OVERRIDE_MAP.items():
        value = getattr(overrides, attr)
        if value is not None:
            config.setdefault(section, {})[key] = value


def load_seed_config() -> dict[str, Any]:
    """Load ``seed.defaults.json`` (next to this file) and overlay ``DEFAULT_*``.

    One file for every environment: the base values live in the JSON, and any
    ``DEFAULT_*`` overrides in ``.env`` are overlaid onto the org/team/admin-user
    fields (see :func:`_apply_overrides`).
    """
    path = Path(__file__).resolve().parent / "seed.defaults.json"
    if not path.exists():
        raise FileNotFoundError(f"Seed config not found: {path}")
    with open(path) as f:
        config = cast(dict[str, Any], json.load(f))
    _apply_overrides(config, SeedOverrides())
    return config


async def seed_roles(session: AsyncSession, config: dict[str, Any]) -> None:
    """Upsert default roles — keep description and permissions in sync with config.

    Inserting a new role on first run, and re-syncing description + permissions
    on subsequent runs so config edits (e.g., adding a new permission) take
    effect without a manual UPDATE. Roles are matched by name.
    """
    for role_data in config.get("roles", []):
        name = role_data["name"]
        description = role_data.get("description", "")
        permissions = role_data.get("permissions", [])
        existing = (
            await session.execute(select(Role).where(Role.name == name))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Role(
                    id=str(uuid.uuid4()),
                    name=name,
                    description=description,
                    permissions=permissions,
                )
            )
            print(f"  Created role: {name}")
            continue
        if existing.description != description or list(existing.permissions or []) != list(
            permissions
        ):
            existing.description = description
            existing.permissions = permissions
            print(f"  Updated role: {name}")
        else:
            print(f"  Role already up to date: {name}")


async def seed_default_org(session: AsyncSession, config: dict[str, Any]) -> Org:
    """Create a default organization and team."""
    org_cfg = config.get("org", {})
    slug = org_cfg.get("slug")
    if not slug:
        raise ValueError("org.slug is required in seed config (seed.defaults.json)")
    result = await session.execute(select(Org).where(Org.slug == slug))
    org = result.scalar_one_or_none()
    if org is None:
        org = Org(
            id=str(uuid.uuid4()),
            name=org_cfg.get("name", "Default Organization"),
            slug=slug,
            settings=org_cfg.get("settings", {}),
        )
        session.add(org)
        await session.flush()
        print(f"  Created default org: {org.slug}")
    else:
        print(f"  Default org already exists: {org.slug}")

    team_cfg = config.get("team", {})
    team_name = team_cfg.get("name", "Default Team")
    team_slug = team_cfg.get("slug") or _default_team_slug(team_name)
    result = await session.execute(
        select(Team).where(Team.org_id == org.id, Team.name == team_name)
    )
    if result.scalar_one_or_none() is None:
        team = Team(
            id=str(uuid.uuid4()),
            name=team_name,
            slug=team_slug,
            org_id=org.id,
        )
        session.add(team)
        print(f"  Created default team: {team.name} (slug={team.slug})")
    else:
        print("  Default team already exists")

    return org


async def seed_admin_user(session: AsyncSession, org: Org, config: dict[str, Any]) -> User:
    """Ensure an admin user exists with org, role, and local password.

    If the user was created via SSO (no password hash), a local password
    is set so CLI/script workflows work.
    """
    admin_cfg = config.get("admin_user", {})
    email = admin_cfg.get("email", "admin@example.com")
    default_password = admin_cfg.get("password", "changeme123")
    role_name = admin_cfg.get("role", "platform_admin")

    # Find the role by name
    role_result = await session.execute(select(Role).where(Role.name == role_name))
    role = role_result.scalar_one_or_none()

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            full_name=admin_cfg.get("full_name", "Admin User"),
            hashed_password=hash_password(default_password),
            is_active=True,
            org_id=org.id,
            role_id=role.id if role else None,
        )
        session.add(user)
        print(f"  Created admin user: {email} (password: {default_password})")
    else:
        changed = False
        if not user.org_id:
            user.org_id = org.id
            changed = True
            print(f"  Set org_id for: {email}")
        if not user.hashed_password:
            user.hashed_password = hash_password(default_password)
            changed = True
            print(f"  Set local password for SSO user: {email} (password: {default_password})")
        if not user.role_id and role:
            user.role_id = role.id
            changed = True
            print(f"  Set {role_name} role for: {email}")
        if not changed:
            print(f"  Admin user already configured: {email}")

    return user


async def seed_llm_provider(
    session: AsyncSession, org: Org, admin: User, config: dict[str, Any]
) -> None:
    """Upsert the default LLM provider that powers the Platform Assistant.

    Written straight to the DB — like the rest of seeding, and mirroring what
    the auth-service create endpoint does (Fernet-encrypt the key at rest, and
    enforce a single default per org) — so a fresh deployment has a provider
    before ``register_platform_assistant`` runs.

    Skipped when ``DEFAULT_LLM_API_KEY`` is unset (a keyless provider can't
    serve the assistant) or when ``SECRETS_ENCRYPTION_KEY`` is absent (the key
    can't be stored at rest without it). In both cases roles/org/team/admin are
    still seeded — only the provider is skipped, with an actionable hint.
    Idempotent: matched by slug, re-syncing its fields on subsequent runs.
    """
    provider = _llm_provider_config(config)
    api_key = provider.get("api_key")
    if not api_key:
        print(
            "  Skipping LLM provider: DEFAULT_LLM_API_KEY not set "
            "(a keyless provider can't serve the Platform Assistant)."
        )
        return
    if not get_settings().secrets_encryption_key:
        print(
            "  Skipping LLM provider: DEFAULT_LLM_API_KEY is set but "
            "SECRETS_ENCRYPTION_KEY is not — it's needed to store the key at rest."
        )
        print('    Generate one: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
        return

    slug = provider.get("slug")
    if not slug:
        raise ValueError("llm_provider.slug is required in seed config (seed.defaults.json)")
    default_model = provider.get("default_model")
    if not default_model:
        raise ValueError("llm_provider.default_model is required in seed config")

    name = provider.get("name", slug)
    provider_type = provider.get("provider_type", "openai_compatible")
    base_url = provider.get("base_url")
    supported_models = provider.get("supported_models", [])
    max_tokens = provider.get("max_tokens")
    is_default = provider.get("is_default", True)
    encrypted = encrypt_value(api_key)

    # A single default per org (matches the auth-service create endpoint):
    # clear any other default before this one is (re)set.
    if is_default:
        await session.execute(
            update(LLMProvider)
            .where(
                LLMProvider.org_id == org.id,
                LLMProvider.is_default.is_(True),
                LLMProvider.slug != slug,
            )
            .values(is_default=False)
        )

    existing = (
        await session.execute(select(LLMProvider).where(LLMProvider.slug == slug))
    ).scalar_one_or_none()

    if existing is None:
        session.add(
            LLMProvider(
                id=str(uuid.uuid4()),
                name=name,
                slug=slug,
                provider_type=provider_type,
                base_url=base_url,
                encrypted_api_key=encrypted,
                default_model=default_model,
                supported_models=supported_models,
                max_tokens=max_tokens,
                is_default=is_default,
                is_active=True,
                org_id=org.id,
                created_by=admin.id,
            )
        )
        print(f"  Created LLM provider: {slug}")
    else:
        existing.name = name
        existing.provider_type = provider_type
        existing.base_url = base_url
        existing.encrypted_api_key = encrypted
        existing.default_model = default_model
        existing.supported_models = supported_models
        existing.max_tokens = max_tokens
        existing.is_default = is_default
        print(f"  Updated LLM provider: {slug}")


async def seed() -> None:
    """Run all seed operations."""
    print("Seeding database...")
    config = load_seed_config()

    engine = get_async_engine()
    factory = get_session_factory()

    async with factory() as session:
        await seed_roles(session, config)
        org = await seed_default_org(session, config)
        admin = await seed_admin_user(session, org, config)
        await seed_llm_provider(session, org, admin, config)
        await session.commit()

    print("Seeding complete.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
