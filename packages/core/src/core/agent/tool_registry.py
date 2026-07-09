"""Global registry for agent tool functions.

Agent packages self-register their tools by calling ``get_tool_registry().register_set()``
on import. The ``agent_service`` imports known agent packages at startup so their tools
are available for runtime resolution by ``build_agent_from_definition()``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry that maps tool function names to their implementations.

    Tools are registered by function name. Multiple tools can be registered
    at once via ``register_set()``. The registry is a flat namespace — no
    tool-set grouping (tool names must be unique).
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, fn: Callable[..., Any]) -> None:
        """Register a single tool function by its ``__name__``."""
        name = fn.__name__
        if name in self._tools:
            logger.warning("Tool '%s' is already registered — overwriting", name)
        self._tools[name] = fn

    def register_set(self, fns: list[Callable[..., Any]]) -> None:
        """Register a list of tool functions."""
        for fn in fns:
            self.register(fn)

    def get(self, name: str) -> Callable[..., Any] | None:
        """Look up a tool by name. Returns None if not found."""
        return self._tools.get(name)

    def resolve(self, names: list[str]) -> list[Callable[..., Any]]:
        """Resolve multiple tool names into a list of functions.

        Unknown names are logged as warnings and skipped.
        """
        resolved = []
        for name in names:
            fn = self.get(name)
            if fn is not None:
                resolved.append(fn)
            else:
                logger.warning("Unknown tool '%s' — skipping", name)
        return resolved

    def list_all(self) -> dict[str, Callable[..., Any]]:
        """Return a copy of the internal mapping."""
        return dict(self._tools)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def clear(self) -> None:
        """Remove all registered tools (useful for testing)."""
        self._tools.clear()


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global ToolRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
