"""Platform tools for the Platform Assistant agent.

Each tool makes authenticated API calls through the gateway using the
user's JWT token, so RBAC scoping is respected — users only see
resources they have access to.

Tools receive a ``PlatformDeps`` dependency from PydanticAI's RunContext
which carries the JWT and gateway URL.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, cast

import httpx
from pydantic_ai import RunContext

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0

# Entry-point group through which external packages can contribute extra
# tools to the built-in Platform Assistant agent by declaring a
# ``techneos.platform_assistant_tools`` entry point. Keeps core free of any
# hard dependency on optional tool content.
#
# At agent-service startup, packages that declare techneos.platform_assistant_tools
# entry points are pip-installed from the configured package index (DevPI
# locally, a hosted index in prod) before this discovery runs. See
# agent_service/main.py:_install_registered_tool_packages().
_EXTRA_TOOLS_ENTRY_POINT_GROUP = "techneos.platform_assistant_tools"


@dataclass
class PlatformDeps:
    """Dependencies injected into platform tools via PydanticAI RunContext."""

    jwt_token: str
    gateway_url: str = "http://localhost:8000"


async def _gateway_get(
    ctx: RunContext[PlatformDeps], path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make an authenticated GET to the gateway."""
    deps = ctx.deps
    url = f"{deps.gateway_url}{path}"
    headers = {"Authorization": f"Bearer {deps.jwt_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())


async def _gateway_post(ctx: RunContext[PlatformDeps], path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make an authenticated POST to the gateway."""
    deps = ctx.deps
    url = f"{deps.gateway_url}{path}"
    headers = {
        "Authorization": f"Bearer {deps.jwt_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=body or {}, headers=headers)
        resp.raise_for_status()
        return cast(dict[Any, Any], resp.json())


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


async def list_datasets(ctx: RunContext[PlatformDeps], limit: int = 10) -> dict[str, Any]:
    """List datasets available on the platform.

    Use this tool when the user asks about available datasets, data,
    or what datasets they can access.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        limit: Maximum results to return. Defaults to 10.

    Returns:
        A dict with ``items`` list and ``total`` count of available datasets.
    """
    try:
        return await _gateway_get(ctx, "/api/v1/datasets", {"limit": str(limit)})
    except httpx.HTTPStatusError as exc:
        logger.warning("list_datasets failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("list_datasets request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def get_dataset_info(ctx: RunContext[PlatformDeps], dataset_id: str) -> dict[str, Any]:
    """Get detailed information about a specific dataset.

    Use this tool when the user asks about a particular dataset by ID
    or wants to see its properties, description, or metadata.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        dataset_id: The dataset UUID.

    Returns:
        A dict with dataset properties.
    """
    try:
        return await _gateway_get(ctx, f"/api/v1/datasets/{dataset_id}")
    except httpx.HTTPStatusError as exc:
        logger.warning("get_dataset_info failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("get_dataset_info request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def list_tools(ctx: RunContext[PlatformDeps], limit: int = 10) -> dict[str, Any]:
    """List computational tools available on the platform.

    Use this tool when the user asks about available tools, software,
    or computational methods they can use.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        limit: Maximum results to return. Defaults to 10.

    Returns:
        A dict with ``items`` list and ``total`` count of available tools.
    """
    try:
        return await _gateway_get(ctx, "/api/v1/tools", {"limit": str(limit)})
    except httpx.HTTPStatusError as exc:
        logger.warning("list_tools failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("list_tools request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def get_tool_info(ctx: RunContext[PlatformDeps], tool_id: str) -> dict[str, Any]:
    """Get detailed information about a specific tool.

    Use this tool when the user asks about a particular tool by ID
    or wants to see its description, versions, or configuration.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        tool_id: The tool UUID.

    Returns:
        A dict with tool properties including versions.
    """
    try:
        return await _gateway_get(ctx, f"/api/v1/tools/{tool_id}")
    except httpx.HTTPStatusError as exc:
        logger.warning("get_tool_info failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("get_tool_info request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def list_pipelines(ctx: RunContext[PlatformDeps], limit: int = 10) -> dict[str, Any]:
    """List pipelines available on the platform.

    Use this tool when the user asks about available pipelines,
    workflows, or automated processes.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        limit: Maximum results to return. Defaults to 10.

    Returns:
        A dict with ``items`` list and ``total`` count of available pipelines.
    """
    try:
        return await _gateway_get(ctx, "/api/v1/pipelines", {"limit": str(limit)})
    except httpx.HTTPStatusError as exc:
        logger.warning("list_pipelines failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("list_pipelines request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def get_pipeline_info(ctx: RunContext[PlatformDeps], pipeline_id: str) -> dict[str, Any]:
    """Get detailed information about a specific pipeline.

    Use this tool when the user asks about a particular pipeline by ID
    or wants to see its steps, parameters, or configuration.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        pipeline_id: The pipeline UUID.

    Returns:
        A dict with pipeline properties including steps and parameters.
    """
    try:
        return await _gateway_get(ctx, f"/api/v1/pipelines/{pipeline_id}")
    except httpx.HTTPStatusError as exc:
        logger.warning("get_pipeline_info failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("get_pipeline_info request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def list_agents(ctx: RunContext[PlatformDeps], limit: int = 10) -> dict[str, Any]:
    """List AI agents available on the platform.

    Use this tool when the user asks about available agents,
    what agents they can use, or wants an overview of AI capabilities.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        limit: Maximum results to return. Defaults to 10.

    Returns:
        A dict with ``items`` list and ``total`` count of available agents.
    """
    try:
        return await _gateway_get(ctx, "/api/v1/agents", {"limit": str(limit)})
    except httpx.HTTPStatusError as exc:
        logger.warning("list_agents failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("list_agents request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def get_agent_info(ctx: RunContext[PlatformDeps], agent_id: str) -> dict[str, Any]:
    """Get detailed information about a specific AI agent.

    Use this tool when the user asks about a particular agent by ID
    or wants to see its capabilities, tools, or configuration.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        agent_id: The agent definition UUID.

    Returns:
        A dict with agent properties including tools and system prompt.
    """
    try:
        return await _gateway_get(ctx, f"/api/v1/agents/{agent_id}")
    except httpx.HTTPStatusError as exc:
        logger.warning("get_agent_info failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("get_agent_info request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def list_apps(ctx: RunContext[PlatformDeps], limit: int = 10) -> dict[str, Any]:
    """List registered applications on the platform.

    Use this tool when the user asks about available apps, web UIs,
    or frontend applications.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        limit: Maximum results to return. Defaults to 10.

    Returns:
        A dict with ``items`` list and ``total`` count of available apps.
    """
    try:
        return await _gateway_get(ctx, "/api/v1/apps", {"limit": str(limit)})
    except httpx.HTTPStatusError as exc:
        logger.warning("list_apps failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("list_apps request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def get_app_info(ctx: RunContext[PlatformDeps], app_id: str) -> dict[str, Any]:
    """Get detailed information about a specific registered application.

    Use this tool when the user asks about a particular app by ID
    or wants to see its URL, description, or configuration.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        app_id: The app UUID.

    Returns:
        A dict with app properties including name, URL, and description.
    """
    try:
        return await _gateway_get(ctx, f"/api/v1/apps/{app_id}")
    except httpx.HTTPStatusError as exc:
        logger.warning("get_app_info failed: %s", exc)
        return {"error": f"API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("get_app_info request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def get_platform_overview(ctx: RunContext[PlatformDeps]) -> dict[str, Any]:
    """Get a comprehensive overview of platform resources available to the user.

    Use this tool when the user asks general questions like "what's available",
    "what can I do", or "show me an overview of the platform".

    Args:
        ctx: PydanticAI run context with platform dependencies.

    Returns:
        A dict with all resource categories, each containing ``items``,
        ``total``, and an ``available`` status flag.
    """
    overview: dict[str, Any] = {}

    resources = [
        ("datasets", "/api/v1/datasets", {"limit": "10"}),
        ("tools", "/api/v1/tools", {"limit": "10"}),
        ("pipelines", "/api/v1/pipelines", {"limit": "10"}),
        ("agents", "/api/v1/agents", {"limit": "10"}),
        ("apps", "/api/v1/apps", {"limit": "10"}),
    ]

    for key, path, params in resources:
        try:
            data = await _gateway_get(ctx, path, params)
            items = data.get("items", [])
            total = data.get("total", len(items))
            overview[key] = {
                "items": items,
                "total": total,
                "available": True,
            }
        except Exception:
            overview[key] = {"items": [], "total": 0, "available": False}

    return overview


async def delegate_to_agent(ctx: RunContext[PlatformDeps], agent_id: str, task: str) -> str:
    """Delegate a task to another AI agent and return its response.

    Use this tool when the user's request would be better handled by a
    specialized agent (e.g., ChEMBL research agent for drug compound queries).
    First use list_agents to find available agents, then delegate.

    The sub-agent will be executed directly and its full response returned.

    Args:
        ctx: PydanticAI run context with platform dependencies.
        agent_id: The UUID or slug of the agent to delegate to.
        task: The task/prompt to send to the sub-agent.

    Returns:
        The sub-agent's complete text response.
    """
    from sqlalchemy import select

    from core.agent.bridge import build_agent_from_definition
    from core.database.postgres import get_async_session_context
    from core.models.agent import AgentDefinition

    try:
        async with get_async_session_context() as session:
            result = await session.execute(
                select(AgentDefinition).where(AgentDefinition.id == agent_id)
            )
            agent_def = result.scalar_one_or_none()

            if agent_def is None:
                result = await session.execute(
                    select(AgentDefinition).where(AgentDefinition.slug == agent_id)
                )
                agent_def = result.scalar_one_or_none()

        if agent_def is None:
            return f"Agent with ID '{agent_id}' not found."

        deps_type = platform_deps_for(agent_def)
        pydantic_agent = build_agent_from_definition(agent_def, deps_type=deps_type)

        run_kwargs: dict[str, Any] = {"user_prompt": task}
        if deps_type is not None:
            deps = ctx.deps
            run_kwargs["deps"] = deps_type(
                jwt_token=deps.jwt_token, gateway_url=deps.gateway_url
            )

        result = await pydantic_agent.run(**run_kwargs)
        return result.output if hasattr(result, "output") else str(result.data)

    except Exception as exc:
        logger.error("delegate_to_agent failed: %s", exc)
        return f"Delegation failed: {type(exc).__name__}: {exc}"


# Built-in tools that ship with the platform-assistant package. These all talk
# to the gateway via authenticated HTTPS — uniform auth/scope/audit story.
PLATFORM_TOOLS_BUILTIN: list[Callable[..., Any]] = [
    list_datasets,
    get_dataset_info,
    list_tools,
    get_tool_info,
    list_pipelines,
    get_pipeline_info,
    list_agents,
    get_agent_info,
    list_apps,
    get_app_info,
    get_platform_overview,
    delegate_to_agent,
]


def load_extra_platform_tools() -> list[Callable[..., Any]]:
    """Discover Platform Assistant tools contributed by catalog packages.

    Looks up the ``techneos.platform_assistant_tools`` entry-point group via
    importlib.metadata. Each entry point is expected to resolve to a
    callable (typically an async function) that the Platform Assistant
    agent can invoke. Loading failures for a single entry point are
    logged and skipped — they never break import of core.

    This is the seam that lets catalog/tools/* contribute optional
    inline tools without core depending on any catalog package.
    """
    extras: list[Callable[..., Any]] = []
    try:
        eps = entry_points(group=_EXTRA_TOOLS_ENTRY_POINT_GROUP)
    except Exception as exc:
        logger.warning("Failed to enumerate Platform Assistant tool entry points: %s", exc)
        return extras

    for ep in eps:
        try:
            fn = ep.load()
        except Exception as exc:
            logger.warning(
                "Skipping Platform Assistant tool entry point %r (load failed: %s)", ep.name, exc
            )
            continue
        if not callable(fn):
            logger.warning(
                "Skipping Platform Assistant tool entry point %r (resolved object is not callable)",
                ep.name,
            )
            continue
        extras.append(fn)
        logger.info("Loaded Platform Assistant tool from entry point: %s", ep.name)
    return extras


# Runtime tool list: built-ins + whatever catalog packages contribute via
# the techneos.platform_assistant_tools entry-point group at install time.
PLATFORM_TOOLS: list[Callable[..., Any]] = [*PLATFORM_TOOLS_BUILTIN, *load_extra_platform_tools()]


def platform_deps_for(agent_def: Any) -> type[PlatformDeps] | None:
    """Return ``PlatformDeps`` if an agent needs platform-tool access, else ``None``.

    An agent needs ``PlatformDeps`` when its slug marks it as the platform
    assistant, or when any of its named tools is a platform tool. This is the
    single source of that decision — used both at build time (the agent's
    ``deps_type``) and run time (the deps instance) by agent-service and by the
    ``delegate_to_agent`` tool above.
    """
    slug = getattr(agent_def, "slug", "") or ""
    if "platform" in slug or "assistant" in slug:
        return PlatformDeps
    names = set(agent_def.tools or [])
    if names:
        platform_tool_names = {fn.__name__ for fn in PLATFORM_TOOLS}
        if names & platform_tool_names:
            return PlatformDeps
    return None
