"""Platform Assistant routes — dedicated chat endpoint with streaming delegation.

The Platform Assistant is a built-in, always-available agent defined by
the AgentDefinition row with is_platform=True.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import traceback
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from platform_assistant.bridge import (
    build_platform_assistant,
    load_platform_assistant_config,
)
from platform_assistant.config import PLATFORM_ASSISTANT_PROMPT
from platform_assistant.tools import PlatformDeps, platform_deps_for
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.crud.agents import get_agent_by_id_or_slug, get_platform_agent
from agent_service.crud.conversations import (
    create_agentic_run,
    get_agentic_run_messages,
)
from agent_service.crud.runs import create_agentic_task, update_agentic_task
from core.agent.bridge import build_agent_from_definition
from core.agent.registry import load_providers_from_db
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.config import get_settings
from core.database.postgres import get_async_session, get_async_session_context
from core.models.common import TokenPayload
from core.schemas.agent import AgenticTaskUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------


class AssistantChatRequest(BaseModel):
    """Request body for the assistant chat endpoint."""

    message: str = Field(min_length=1)
    conversation_id: str | None = None


class AssistantConfigResponse(BaseModel):
    """Response for assistant configuration."""

    id: str | None = None
    provider_slug: str | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    tools: list[str] = Field(default_factory=list)
    max_tokens: int | None = None
    temperature: float | None = None


class AssistantConfigUpdate(BaseModel):
    """Update request for assistant configuration."""

    provider_slug: str | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    max_tokens: int | None = None
    temperature: float | None = None


class DelegateRequest(BaseModel):
    """Request body for the delegate endpoint (used internally by the tool fallback)."""

    agent_id: str
    task: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse_event(data: dict[str, Any]) -> str:
    """Format a dict as an SSE event."""
    return f"data: {json.dumps(data)}\n\n"


def _json_safe(obj: list[Any]) -> list[Any]:
    """Ensure objects are JSON-serializable dicts."""
    result = []
    for item in obj:
        if isinstance(item, dict):
            try:
                json.dumps(item)
                result.append(item)
            except (TypeError, ValueError):
                result.append({"content": str(item)})
        else:
            result.append({"content": str(item)})
    return result


def _require_org(current_user: TokenPayload) -> str:
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


# ---------------------------------------------------------------------------
# Sub-agent streaming execution
# ---------------------------------------------------------------------------


async def _stream_sub_agent(
    agent_def: Any,
    task: str,
    jwt_token: str,
    gateway_url: str,
) -> AsyncIterator[tuple[str, str]]:
    """Run a sub-agent with streaming, yielding (event_type, data) tuples.

    Yields:
        ("delegation_token", text) for each streamed token
        ("delegation_completed", full_text) when done
        ("delegation_error", error_message) on failure
    """
    try:
        deps_type = platform_deps_for(agent_def)
        pydantic_agent = build_agent_from_definition(
            agent_def,
            deps_type=deps_type,
            default_prompt=PLATFORM_ASSISTANT_PROMPT if deps_type else None,
        )

        run_kwargs: dict[str, Any] = {"user_prompt": task}
        if deps_type is not None:
            run_kwargs["deps"] = deps_type(jwt_token=jwt_token, gateway_url=gateway_url)

        full_text = ""
        async with pydantic_agent.run_stream(**run_kwargs) as result:
            async for text in result.stream_text(delta=True):
                full_text += text
                yield ("delegation_token", text)

        yield ("delegation_completed", full_text)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Sub-agent delegation failed: %s", error_msg)
        yield ("delegation_error", error_msg)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/chat")
async def assistant_chat(
    data: AssistantChatRequest,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Stream a chat response from the Platform Assistant.

    This endpoint builds the Platform Assistant from its DB config (not from the
    agents table), handles conversation history, and supports streaming
    delegation to sub-agents.
    """
    settings = get_settings()
    org_id = _require_org(current_user)

    # Load platform assistant config from DB
    config = await load_platform_assistant_config()

    # Handle conversation
    platform_agent = await get_platform_agent(session)
    conversation_id = data.conversation_id
    if not conversation_id:
        conv = await create_agentic_run(
            session,
            agent_id=str(platform_agent.id) if platform_agent else None,
            org_id=org_id,
            user_id=current_user.sub,
            title=data.message[:100],
        )
        conversation_id = str(conv.id)

    # Load message history
    message_history = None
    if conversation_id:
        raw_messages = await get_agentic_run_messages(session, conversation_id)
        if raw_messages:
            from pydantic import TypeAdapter
            from pydantic_ai.messages import ModelMessage

            try:
                adapter = TypeAdapter(list[ModelMessage])
                message_history = adapter.validate_python(raw_messages)
            except Exception as exc:
                logger.warning("Failed to deserialize message history: %s", exc)
                message_history = None

    # Create a run record (use platform agent ID)
    run = await create_agentic_task(
        session,
        agent_id=str(platform_agent.id) if platform_agent else None,
        task=data.message,
        context={},
        org_id=org_id,
        user_id=current_user.sub,
        agentic_run_id=conversation_id,
    )
    await session.commit()
    run_id = str(run.id)

    # Extract JWT
    auth_header = request.headers.get("authorization", "")
    jwt_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    deps = PlatformDeps(jwt_token=jwt_token, gateway_url=settings.gateway_url)

    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events using agent.iter() for real-time step visibility.

        Uses PydanticAI's iter() API to emit tool calls and results as they happen,
        rather than waiting for the entire run to complete.
        """
        messages: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        full_text = ""
        tokens_used = 0
        emitted_tool_returns: set[str] = set()

        yield _sse_event(
            {"type": "run_started", "run_id": run_id, "conversation_id": conversation_id}
        )

        try:
            from pydantic_ai import CallToolsNode, ModelRequestNode
            from pydantic_graph import End

            # Reload providers from DB so that any API key updates
            # (made via the admin UI after service startup) are picked up.
            await load_providers_from_db()
            pydantic_agent = build_platform_assistant(config=config)

            async with get_async_session_context() as db:
                await update_agentic_task(
                    db,
                    run_id,
                    AgenticTaskUpdate(status="running", started_at=datetime.now(UTC)),
                )
                await db.commit()

            iter_kwargs: dict[str, Any] = {"user_prompt": data.message, "deps": deps}
            if message_history:
                iter_kwargs["message_history"] = message_history

            async with pydantic_agent.iter(**iter_kwargs) as agent_run:
                node = agent_run.next_node
                while not isinstance(node, End):
                    if isinstance(node, CallToolsNode):
                        # Model responded with tool calls — emit them NOW before execution
                        response = node.model_response
                        if hasattr(response, "parts"):
                            for part in response.parts:
                                part_kind = getattr(part, "part_kind", None)
                                if part_kind == "tool-call":
                                    tool_name = getattr(part, "tool_name", "")
                                    raw_args = getattr(part, "args", {})
                                    if isinstance(raw_args, str):
                                        try:
                                            raw_args = json.loads(raw_args)
                                        except (json.JSONDecodeError, TypeError):
                                            raw_args = {"raw": raw_args}
                                    tc_info = {"name": tool_name, "args": raw_args}
                                    tool_calls.append(tc_info)
                                    if tool_name == "delegate_to_agent":
                                        yield _sse_event(
                                            {
                                                "type": "delegation_started",
                                                "agent_id": raw_args.get("agent_id", "")
                                                if isinstance(raw_args, dict)
                                                else "",
                                                "task": raw_args.get("task", "")
                                                if isinstance(raw_args, dict)
                                                else "",
                                            }
                                        )
                                    else:
                                        yield _sse_event({"type": "tool_call", **tc_info})

                        # Now execute the tools (this runs delegate_to_agent, etc.)
                        node = await agent_run.next(node)

                        # After tool execution, emit tool results from message history
                        for msg in agent_run.all_messages():
                            if hasattr(msg, "parts"):
                                for part in msg.parts:
                                    part_kind = getattr(part, "part_kind", None)
                                    if part_kind == "tool-return":
                                        part_id = f"{getattr(part, 'tool_name', '')}:{getattr(part, 'tool_call_id', id(part))}"
                                        if part_id in emitted_tool_returns:
                                            continue
                                        emitted_tool_returns.add(part_id)
                                        tool_name = getattr(part, "tool_name", "")
                                        content = getattr(part, "content", "")
                                        result_str = (
                                            content
                                            if isinstance(content, str)
                                            else json.dumps(content)
                                        )
                                        if tool_name == "delegate_to_agent":
                                            yield _sse_event(
                                                {
                                                    "type": "delegation_completed",
                                                    "result": result_str,
                                                }
                                            )
                                        else:
                                            yield _sse_event(
                                                {
                                                    "type": "tool_result",
                                                    "name": tool_name,
                                                    "result": result_str,
                                                }
                                            )

                    elif isinstance(node, ModelRequestNode):
                        # Model is being called — execute and move to next node
                        node = await agent_run.next(node)
                    else:
                        # UserPromptNode or other — just advance
                        node = await agent_run.next(node)

                # Run is complete — extract final text from the End node
                if isinstance(node, End):
                    final_result = node.data
                    if hasattr(final_result, "output"):
                        output = final_result.output
                        if isinstance(output, str):
                            full_text = output
                            yield _sse_event({"type": "token", "text": output})

            # Get usage (pydantic-ai 2.x: `usage` is a RunUsage property, and the
            # token fields were renamed request/response -> input/output).
            usage = agent_run.usage
            if usage:
                tokens_used = (usage.input_tokens or 0) + (usage.output_tokens or 0)

            # Serialize messages for DB using TypeAdapter for proper round-tripping
            try:
                from pydantic import TypeAdapter
                from pydantic_ai.messages import ModelMessage

                adapter = TypeAdapter(list[ModelMessage])
                messages = adapter.dump_python(agent_run.all_messages(), mode="json")
            except Exception:
                # Fallback: manual serialization
                for msg in agent_run.all_messages():
                    try:
                        if hasattr(msg, "model_dump"):
                            msg_dict = msg.model_dump(mode="json")
                        elif dataclasses.is_dataclass(msg):
                            msg_dict = dataclasses.asdict(cast(Any, msg))
                        else:
                            msg_dict = {"role": str(type(msg).__name__), "content": str(msg)}
                    except Exception:
                        msg_dict = {"role": str(type(msg).__name__), "content": str(msg)}
                    messages.append(msg_dict)

            final_text = full_text

            async with get_async_session_context() as db:
                await update_agentic_task(
                    db,
                    run_id,
                    AgenticTaskUpdate(
                        status="completed",
                        result={"response": final_text},
                        messages=_json_safe(messages),
                        tool_calls=_json_safe(tool_calls),
                        tokens_used=tokens_used,
                        finished_at=datetime.now(UTC),
                    ),
                )
                await db.commit()

            yield _sse_event(
                {
                    "type": "completed",
                    "text": final_text,
                    "run_id": run_id,
                    "conversation_id": conversation_id,
                    "tokens_used": tokens_used,
                }
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Platform assistant run %s failed: %s\n%s",
                run_id,
                error_msg,
                traceback.format_exc(),
            )

            try:
                async with get_async_session_context() as db:
                    await update_agentic_task(
                        db,
                        run_id,
                        AgenticTaskUpdate(
                            status="failed",
                            error_message=error_msg,
                            result={"response": f"Error: {error_msg}"},
                            messages=_json_safe(messages),
                            tool_calls=_json_safe(tool_calls),
                            finished_at=datetime.now(UTC),
                        ),
                    )
                    await db.commit()
            except Exception:
                logger.exception("Failed to update run %s status to failed", run_id)

            yield _sse_event({"type": "error", "message": error_msg, "run_id": run_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/delegate")
async def delegate_to_sub_agent(
    data: DelegateRequest,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Execute a sub-agent and stream its response.

    Used as a fallback by the delegate_to_agent tool when not intercepted
    at the streaming level.
    """
    settings = get_settings()

    agent_def = await get_agent_by_id_or_slug(session, data.agent_id)

    auth_header = request.headers.get("authorization", "")
    jwt_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    async def event_generator() -> AsyncIterator[str]:
        async for event_type, text in _stream_sub_agent(
            agent_def, data.task, jwt_token, settings.gateway_url
        ):
            yield _sse_event({"type": event_type, "text": text})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Admin config endpoints
# ---------------------------------------------------------------------------


@router.get("/config", response_model=AssistantConfigResponse)
async def get_assistant_config(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> AssistantConfigResponse:
    """Get the current Platform Assistant configuration."""
    from core.models.agent import AgentDefinition

    result = await session.execute(
        select(AgentDefinition).where(AgentDefinition.is_platform.is_(True))
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        return AssistantConfigResponse()

    mc = agent.model_config_ or {}
    return AssistantConfigResponse(
        id=agent.id,
        provider_slug=mc.get("provider"),
        model_name=mc.get("model"),
        system_prompt=agent.system_prompt,
        tools=agent.tools or [],
        max_tokens=mc.get("max_tokens"),
        temperature=mc.get("temperature"),
    )


@router.put("/config", response_model=AssistantConfigResponse)
async def update_assistant_config(
    data: AssistantConfigUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("assistant_config", "update", "platform")),
) -> AssistantConfigResponse:
    """Update the platform assistant configuration (admin)."""
    from core.models.agent import AgentDefinition

    result = await session.execute(
        select(AgentDefinition).where(AgentDefinition.is_platform.is_(True))
    )
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail="Platform agent not found — run database seed to create it",
        )

    mc = dict(agent.model_config_ or {})
    update_data = data.model_dump(exclude_unset=True)

    if "provider_slug" in update_data:
        mc["provider"] = update_data.pop("provider_slug")
    if "model_name" in update_data:
        mc["model"] = update_data.pop("model_name")
    if "max_tokens" in update_data:
        mc["max_tokens"] = update_data.pop("max_tokens")
    if "temperature" in update_data:
        mc["temperature"] = update_data.pop("temperature")
    if "system_prompt" in update_data:
        agent.system_prompt = update_data.pop("system_prompt")
    if "tools" in update_data:
        agent.tools = update_data.pop("tools")

    agent.model_config_ = mc

    await session.commit()
    await session.refresh(agent)

    mc = agent.model_config_ or {}
    return AssistantConfigResponse(
        id=agent.id,
        provider_slug=mc.get("provider"),
        model_name=mc.get("model"),
        system_prompt=agent.system_prompt,
        tools=agent.tools or [],
        max_tokens=mc.get("max_tokens"),
        temperature=mc.get("temperature"),
    )
