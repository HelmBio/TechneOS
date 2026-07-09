"""Bridge for building the Platform Assistant PydanticAI agent.

Loads configuration from the database ``AgentDefinition`` row (``is_platform=True``)
or falls back to module-level defaults.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from core.agent.models import build_model_from_provider
from core.agent.tool_registry import get_tool_registry
from platform_assistant.config import (
    PLATFORM_ASSISTANT_PROMPT,
    default_platform_assistant_config,
)
from platform_assistant.tools import PLATFORM_TOOLS, PlatformDeps

logger = logging.getLogger(__name__)


async def load_platform_assistant_config() -> dict[str, Any] | None:
    """Load the Platform Assistant config from the platform AgentDefinition.

    Returns None if no platform agent exists (run the registration script first).
    """
    from sqlalchemy import select

    from core.database.postgres import get_async_session_context
    from core.models.agent import AgentDefinition

    try:
        async with get_async_session_context() as session:
            result = await session.execute(
                select(AgentDefinition).where(AgentDefinition.is_platform.is_(True))
            )
            agent = result.scalar_one_or_none()
            if agent is None:
                return None
            mc = agent.model_config_ or {}
            return {
                "provider_slug": mc.get("provider"),
                "model_name": mc.get("model"),
                "system_prompt": agent.system_prompt,
                "tools": agent.tools or [],
                "max_tokens": mc.get("max_tokens"),
                "temperature": mc.get("temperature"),
            }
    except Exception as e:
        logger.warning("Failed to load platform assistant config from DB: %s", e)
        return None


def build_platform_assistant(
    provider_slug: str | None = None,
    model_name: str | None = None,
    system_prompt: str | None = None,
    config: dict[str, Any] | None = None,
) -> Agent[PlatformDeps]:
    """Build a PydanticAI Agent configured as the Platform Assistant.

    This agent uses ``PlatformDeps`` as its dependency type so that
    platform tools can make authenticated API calls through the gateway.

    If ``config`` is provided (from DB via ``load_platform_assistant_config``),
    it is used as the base configuration. Explicit parameters override config values.
    """
    cfg = config or default_platform_assistant_config()
    resolved_provider = provider_slug or cfg.get("provider_slug")
    resolved_model = model_name or cfg.get("model_name")
    resolved_prompt = system_prompt or cfg.get("system_prompt") or PLATFORM_ASSISTANT_PROMPT

    tool_names = cfg.get("tools") or []
    if tool_names:
        reg = get_tool_registry()
        tools = reg.resolve(tool_names)
        if not tools:
            tools = list(PLATFORM_TOOLS)
    else:
        tools = list(PLATFORM_TOOLS)

    model = build_model_from_provider(resolved_provider, resolved_model)

    return Agent(
        model=model,
        deps_type=PlatformDeps,
        instructions=resolved_prompt,
        tools=tools,
        retries=2,
    )
