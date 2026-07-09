"""Idempotent seed for the built-in Platform Assistant AgentDefinition.

The Platform Assistant is a built-in, always-on agent. Rather than relying on a
manual ``build_and_register.py`` run, this guarantees the ``AgentDefinition`` row
exists. It lives in the platform-assistant package (which ships inside the
agent-service image), so it can pull the defaults from ``platform_assistant.config``
without ``core`` ever depending on this package.

Two callers:
  * agent-service startup (best-effort, self-healing — see ``agent_service.main``);
  * the deploy stage, ``python -m platform_assistant.seed``, run after
    ``core.database.seed`` so the owning org + admin already exist.

It only **creates** when missing — it never overwrites a manually configured
assistant. The LLM provider + its API key are still configured separately
(admin UI); this seeds the agent definition only.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_assistant.config import default_platform_assistant_config

logger = logging.getLogger(__name__)

AGENT_SLUG = "platform-assistant"


async def ensure_platform_assistant(session: AsyncSession) -> bool:
    """Create the Platform Assistant AgentDefinition if absent. Idempotent.

    Returns True if it created the row; False if one already existed or no
    ``platform_admin`` user is available yet to own it (e.g. called before
    ``core.database.seed`` on a fresh DB — the caller can retry later).
    """
    from core.models.agent import AgentDefinition
    from core.models.user import Role, User

    existing = (
        await session.execute(
            select(AgentDefinition).where(AgentDefinition.is_platform.is_(True))
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    # Own it with the seeded platform_admin (supplies org_id + created_by).
    admin = (
        await session.execute(
            select(User)
            .join(Role, User.role_id == Role.id)
            .where(Role.name == "platform_admin")
            .limit(1)
        )
    ).scalar_one_or_none()
    if admin is None:
        logger.warning("No platform_admin user yet — skipping Platform Assistant seed")
        return False

    cfg = default_platform_assistant_config()
    session.add(
        AgentDefinition(
            name="Platform Assistant",
            slug=AGENT_SLUG,
            description="Built-in platform assistant — ask about datasets, tools, pipelines, and agents",
            agent_type="conversational",
            framework="custom",
            is_platform=True,
            is_public=True,
            system_prompt=cfg["system_prompt"],
            model_config_={
                "provider": cfg["provider_slug"],
                "model": cfg["model_name"],
                "max_tokens": cfg.get("max_tokens"),
                "temperature": cfg.get("temperature"),
            },
            tools=cfg["tools"],
            org_id=admin.org_id,
            created_by=admin.id,
        )
    )
    await session.flush()
    logger.info("Seeded Platform Assistant AgentDefinition (slug=%s)", AGENT_SLUG)
    return True


async def _seed() -> None:
    from core.database.postgres import get_async_engine, get_session_factory

    engine = get_async_engine()
    factory = get_session_factory()
    async with factory() as session:
        created = await ensure_platform_assistant(session)
        await session.commit()
    print("Platform Assistant: " + ("created" if created else "already present"))
    await engine.dispose()


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
