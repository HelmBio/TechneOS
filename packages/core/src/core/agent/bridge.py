"""Build a PydanticAI Agent from a platform ``AgentDefinition``.

Provider→model bridging lives in ``core.agent.models``;
``build_model_from_provider`` is re-exported here for existing platform imports.
``build_agent_from_definition`` is the generic assembler — it resolves the agent's
tools from the shared ``ToolRegistry`` and wires them to a model. It is deliberately
**free of any platform-assistant knowledge**: callers that need platform tools
(agent-service, and the platform-assistant's own ``delegate_to_agent`` tool) pass the
``deps_type`` / ``default_prompt`` in, via ``platform_assistant.platform_deps_for``.

Tool registration:
  Agent packages self-register their tools with the global ``ToolRegistry`` on import
  (or at agent-service startup). See ``platform_assistant`` and ``chembl_agent``.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from core.agent.models import build_model_from_provider
from core.agent.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)

__all__ = ["build_agent_from_definition", "build_model_from_provider"]


def _resolve_tools(agent_def: Any) -> list[Any]:
    """Resolve an agent's tools from the global ToolRegistry.

    Named tools are looked up by name; an agent with no named tools gets every
    registered tool. Platform tools are registered into the same registry at
    agent-service startup, so no special-casing is needed here.
    """
    reg = get_tool_registry()
    tool_names = set(agent_def.tools or [])
    if not tool_names:
        return list(reg.list_all().values())

    tools = []
    for name in tool_names:
        fn = reg.get(name)
        if fn is not None:
            tools.append(fn)
        else:
            logger.warning("Unknown tool '%s' in agent definition %s", name, agent_def.slug)
    return tools


def build_agent_from_definition(
    agent_def: Any,
    *,
    deps_type: type | None = None,
    default_prompt: str | None = None,
) -> Agent:
    """Build a PydanticAI Agent from an ``AgentDefinition`` ORM model.

    Reads ``model_config_`` (JSONB) for the provider slug and model name,
    ``system_prompt`` for instructions, and ``tools`` (JSONB list) for which tools
    to attach. ``deps_type`` (e.g. ``PlatformDeps``) and ``default_prompt`` are
    supplied by the caller when the agent needs platform-tool dependencies — core
    itself stays free of platform-assistant knowledge.
    """
    model_cfg = agent_def.model_config_ or {}
    model = build_model_from_provider(model_cfg.get("provider"), model_cfg.get("model"))
    tools = _resolve_tools(agent_def)
    instructions = agent_def.system_prompt or default_prompt

    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "tools": tools,
        "retries": 2,
    }
    if deps_type is not None:
        kwargs["deps_type"] = deps_type
    return Agent(**kwargs)
