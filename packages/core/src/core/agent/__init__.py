"""Agent executor protocol and base implementations.

Submodules:
    bridge             — generic AgentDefinition → PydanticAI agent assembler
    providers          — crypto/DB-free LLM provider registry + OpenAI client builder
    models             — build_model_from_provider (provider → PydanticAI model)
    registry           — DB loader on top of `providers` (decrypts keys at the boundary)
    tool_registry      — global registry agent packages self-register their tools into

The built-in Platform Assistant moved to the ``techneos-platform-assistant`` package
(``platform_assistant``); core no longer depends on it.
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class AgentContext(BaseModel):
    """Input context for an agent execution."""

    task: str
    parameters: dict[str, Any] = {}
    context: dict[str, Any] = {}
    tools: list[str] = []
    system_prompt: str | None = None


class AgentResult(BaseModel):
    """Output from an agent execution."""

    status: str  # completed | failed
    result: dict[str, Any] = {}
    messages: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    tokens_used: int | None = None
    error_message: str | None = None


@runtime_checkable
class AgentExecutor(Protocol):
    """Protocol that all agent executors must implement."""

    async def run(self, agent_id: str, context: AgentContext) -> AgentResult: ...


class EchoAgentExecutor:
    """Stub agent executor for testing — echoes back the task."""

    async def run(self, agent_id: str, context: AgentContext) -> AgentResult:
        return AgentResult(
            status="completed",
            result={"echo": context.task},
            messages=[{"role": "assistant", "content": f"Echo: {context.task}"}],
            tool_calls=[],
            tokens_used=0,
        )
