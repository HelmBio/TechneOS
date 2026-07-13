"""Database seeding — create the default roles, org, team, and admin user.

A platform-admin operation, run once after the infrastructure and schema are
up (``make up`` + ``make migrate``) and before any catalog items are
registered. Not part of any shipped wheel and not imported by the services at
runtime — it writes directly to the database.

Config is loaded from ``.techneos.<env>.json`` next to this file (e.g.
``.techneos.development.json``), falling back to ``.techneos.example.json``.
The org, team, and admin-user values can be overridden per deployment with
``DEFAULT_*`` variables in ``.env`` (see ``SeedOverrides``); role definitions
stay in the JSON, since their permission lists are too structured for env vars.

    python setup/database/seed.py   # or: make seed
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, cast

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.providers import hash_password
from core.config import get_settings
from core.database.postgres import get_async_engine, get_session_factory
from core.models.user import Org, Role, Team, User


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


def _default_team_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "team"


def _apply_overrides(config: dict[str, Any], overrides: SeedOverrides) -> None:
    """Overlay any set ``DEFAULT_*`` env values onto the loaded config in place."""
    for attr, (section, key) in _OVERRIDE_MAP.items():
        value = getattr(overrides, attr)
        if value is not None:
            config.setdefault(section, {})[key] = value


def load_seed_config(env: str = "development") -> dict[str, Any]:
    """Load seed configuration for ``env``.

    Tries ``.techneos.<env>.json`` first, then falls back to
    ``.techneos.example.json`` for the base values, then overlays any
    ``DEFAULT_*`` overrides from ``.env`` onto the org/team/admin-user fields.
    """
    seed_dir = Path(__file__).resolve().parent
    candidates = [
        seed_dir / f".techneos.{env}.json",
        seed_dir / ".techneos.example.json",
    ]
    for path in candidates:
        if path.exists():
            with open(path) as f:
                config = cast(dict[str, Any], json.load(f))
            _apply_overrides(config, SeedOverrides())
            return config
    raise FileNotFoundError(f"No seed config found. Tried: {', '.join(str(p) for p in candidates)}")


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
        raise ValueError("org.slug is required in seed config (.techneos.<env>.json)")
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


async def seed() -> None:
    """Run all seed operations."""
    print("Seeding database...")
    config = load_seed_config(get_settings().environment)

    engine = get_async_engine()
    factory = get_session_factory()

    async with factory() as session:
        await seed_roles(session, config)
        org = await seed_default_org(session, config)
        await seed_admin_user(session, org, config)
        await session.commit()

    print("Seeding complete.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
