"""Agentic task routes — submit, list, status, cancel, and SSE streaming."""

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
from platform_assistant.config import PLATFORM_ASSISTANT_PROMPT
from platform_assistant.tools import platform_deps_for
from sqlalchemy.ext.asyncio import AsyncSession

from agent_service.crud.agents import (
    get_agent,
    get_agent_by_id_or_slug,
    resolve_agent_id_filter,
)
from agent_service.crud.conversations import (
    create_agentic_run,
    get_agentic_run_messages,
)
from agent_service.crud.runs import (
    cancel_agentic_task,
    create_agentic_task,
    get_agentic_task,
    list_agentic_tasks,
    update_agentic_task,
)
from core.agent.bridge import build_agent_from_definition
from core.auth.dependencies import get_current_user
from core.auth.rbac import require_permission
from core.auth.scope import build_scope_filters, check_resource_access
from core.config import get_settings
from core.database.postgres import get_async_session, get_async_session_context
from core.models.agent import AgenticTask
from core.models.common import PaginatedResponse, TokenPayload
from core.schemas.agent import (
    AgenticTaskCreate,
    AgenticTaskDetail,
    AgenticTaskResponse,
    AgenticTaskUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_org(current_user: TokenPayload) -> str:
    """Extract org_id from token, raising 403 if absent."""
    if not current_user.org_id:
        raise HTTPException(status_code=403, detail="User is not associated with an organization")
    return current_user.org_id


# ---------------------------------------------------------------------------
# Existing CRUD endpoints (unchanged)
# ---------------------------------------------------------------------------


@router.post("", response_model=AgenticTaskResponse, status_code=201)
async def submit_task(
    data: AgenticTaskCreate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-task", "execute", "own")),
) -> AgenticTaskResponse:
    """Submit a new agentic task.

    Validates the agent exists, merges default parameters with
    user-provided context, and creates the task record.
    """
    org_id = _require_org(current_user)

    # Validate agent exists and check access
    agent = await get_agent_by_id_or_slug(session, data.agent_id)
    check_resource_access(current_user, agent, resource_name="agent")

    # Merge default parameters with user-supplied context
    merged_context = {**data.context, "parameters": {**agent.default_parameters, **data.parameters}}

    # Create the task
    task = await create_agentic_task(
        session,
        agent_id=agent.id,
        task=data.task,
        context=merged_context,
        org_id=org_id,
        user_id=current_user.sub,
    )

    return AgenticTaskResponse.model_validate(task)


@router.get("", response_model=PaginatedResponse)
async def list_tasks_endpoint(
    agent_id: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-task", "read", "own")),
) -> PaginatedResponse:
    """List agentic tasks with optional filters (agent_id accepts id or slug)."""
    agent_id = await resolve_agent_id_filter(session, agent_id)
    scope_filters = build_scope_filters(current_user, AgenticTask, "agentic-task")
    items, total = await list_agentic_tasks(
        session,
        agent_id=agent_id,
        status=status,
        skip=skip,
        limit=limit,
        extra_filters=scope_filters,
    )
    return PaginatedResponse(
        items=[AgenticTaskResponse.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{task_id}", response_model=AgenticTaskDetail)
async def get_task_endpoint(
    task_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-task", "read", "own")),
) -> AgenticTaskDetail:
    """Get an agentic task with inline agent definition info."""
    task = await get_agentic_task(session, task_id)
    check_resource_access(current_user, task, resource_name="agentic-task")
    agent = await get_agent(session, cast(str, task.agent_id))

    # Build base response first (avoids triggering lazy-load on relationships)
    base = AgenticTaskResponse.model_validate(task)
    return AgenticTaskDetail(
        **base.model_dump(),
        agent_name=agent.name,
        agent_slug=agent.slug,
    )


@router.patch("/{task_id}", response_model=AgenticTaskResponse)
async def update_task_endpoint(
    task_id: str,
    data: AgenticTaskUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-task", "update", "own")),
) -> AgenticTaskResponse:
    """Update an agentic task (status, result, messages, tool_calls, etc.).

    Typically called by the agent executor, not end users.
    """
    task = await get_agentic_task(session, task_id)
    check_resource_access(current_user, task, resource_name="agentic-task", write=True)
    task = await update_agentic_task(session, task_id, data)
    return AgenticTaskResponse.model_validate(task)


@router.post("/{task_id}/cancel", response_model=AgenticTaskResponse)
async def cancel_task_endpoint(
    task_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-task", "update", "own")),
) -> AgenticTaskResponse:
    """Cancel a pending or running agentic task."""
    task = await get_agentic_task(session, task_id)
    check_resource_access(current_user, task, resource_name="agentic-task", write=True)
    task = await cancel_agentic_task(session, task_id)
    return AgenticTaskResponse.model_validate(task)


# ---------------------------------------------------------------------------
# SSE streaming endpoint — executes an agentic task with real-time events
# ---------------------------------------------------------------------------


def _sse_event(data: dict[str, Any]) -> str:
    """Format a dict as a Server-Sent Event data line."""
    return f"data: {json.dumps(data)}\n\n"


def _json_safe(obj: object) -> object:
    """Recursively convert an object to JSON-serializable types."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


@router.post("/stream", status_code=200)
async def stream_task(
    data: AgenticTaskCreate,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
    _perm: bool = Depends(require_permission("agentic-task", "execute", "own")),
) -> StreamingResponse:
    """Submit and stream an agentic task via Server-Sent Events.

    Supports multi-turn conversations when ``agentic_run_id`` is provided.
    If ``agentic_run_id`` is not set, a new agentic run is auto-created
    when the agent is a platform assistant (slug contains 'platform' or
    'assistant').

    Creates an ``AgenticTask`` record, builds a PydanticAI agent from the
    ``AgentDefinition``, and streams the execution as SSE events:

    - ``{"type": "run_started", "task_id": "...", "agentic_run_id": "..."}``
    - ``{"type": "token", "text": "..."}`` — streamed text chunks
    - ``{"type": "tool_call", "name": "...", "args": {...}}`` — tool invocation
    - ``{"type": "tool_result", "name": "...", "result": {...}}`` — tool output
    - ``{"type": "completed", "text": "...", "task_id": "..."}`` — final result
    - ``{"type": "error", "message": "..."}`` — if execution fails
    """
    org_id = _require_org(current_user)
    settings = get_settings()

    # Validate agent and access
    agent_def = await get_agent_by_id_or_slug(session, data.agent_id)
    check_resource_access(current_user, agent_def, resource_name="agent")

    # Merge parameters
    merged_context = {
        **data.context,
        "parameters": {**agent_def.default_parameters, **data.parameters},
    }

    # Handle agentic run: use existing or auto-create for assistant agents
    agentic_run_id = data.agentic_run_id
    if not agentic_run_id:
        slug = agent_def.slug or ""
        if "platform" in slug or "assistant" in slug:
            agentic_run = await create_agentic_run(
                session,
                agent_id=agent_def.id,
                org_id=org_id,
                user_id=current_user.sub,
                title=data.task[:100],
            )
            agentic_run_id = str(agentic_run.id)

    # Load message history from prior conversation runs
    message_history = None
    if agentic_run_id:
        raw_messages = await get_agentic_run_messages(session, agentic_run_id)
        if raw_messages:
            from pydantic import TypeAdapter
            from pydantic_ai.messages import ModelMessage

            try:
                adapter = TypeAdapter(list[ModelMessage])
                message_history = adapter.validate_python(raw_messages)
            except Exception as exc:
                logger.warning("Failed to deserialize message history: %s", exc)
                message_history = None

    # Create the task record
    task = await create_agentic_task(
        session,
        agent_id=agent_def.id,
        task=data.task,
        context=merged_context,
        org_id=org_id,
        user_id=current_user.sub,
        agentic_run_id=agentic_run_id,
    )
    await session.commit()
    task_id = str(task.id)

    # Extract JWT for platform tools (if needed)
    auth_header = request.headers.get("authorization", "")
    jwt_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    # Determine if the agent needs PlatformDeps (single source: platform_deps_for).
    deps_type = platform_deps_for(agent_def)
    deps = None
    if deps_type is not None:
        deps = deps_type(jwt_token=jwt_token, gateway_url=settings.gateway_url)

    async def event_generator() -> AsyncIterator[str]:
        """Generate SSE events from PydanticAI agent execution with real-time steps."""
        messages: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        full_text = ""
        tokens_used = 0
        emitted_tool_returns: set[str] = set()

        # Signal task started
        yield _sse_event(
            {
                "type": "run_started",
                "task_id": task_id,
                "agentic_run_id": agentic_run_id,
            }
        )

        try:
            from pydantic_ai import CallToolsNode, ModelRequestNode
            from pydantic_graph import End

            # Build the PydanticAI agent from the definition
            pydantic_agent = build_agent_from_definition(
                agent_def,
                deps_type=deps_type,
                default_prompt=PLATFORM_ASSISTANT_PROMPT if deps_type else None,
            )

            # Mark task as running
            async with get_async_session_context() as db:
                await update_agentic_task(
                    db,
                    task_id,
                    AgenticTaskUpdate(status="running", started_at=datetime.now(UTC)),
                )
                await db.commit()

            # Build run kwargs
            iter_kwargs: dict[str, Any] = {"user_prompt": data.task}
            if deps is not None:
                iter_kwargs["deps"] = deps
            if message_history:
                iter_kwargs["message_history"] = message_history

            # Use iter() for real-time step visibility
            async with pydantic_agent.iter(**iter_kwargs) as agent_run:
                node = agent_run.next_node
                while not isinstance(node, End):
                    if isinstance(node, CallToolsNode):
                        # Emit tool calls immediately before execution
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
                                    yield _sse_event({"type": "tool_call", **tc_info})

                        # Execute the tools
                        node = await agent_run.next(node)

                        # Emit tool results after execution
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
                                        yield _sse_event(
                                            {
                                                "type": "tool_result",
                                                "name": tool_name,
                                                "result": result_str,
                                            }
                                        )

                    elif isinstance(node, ModelRequestNode):
                        node = await agent_run.next(node)
                    else:
                        node = await agent_run.next(node)

                # Extract final text from the End node
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

            # Update DB with completed status
            async with get_async_session_context() as db:
                await update_agentic_task(
                    db,
                    task_id,
                    AgenticTaskUpdate(
                        status="completed",
                        result={"response": final_text},
                        messages=cast("list[dict[str, Any]] | None", _json_safe(messages)),
                        tool_calls=cast("list[dict[str, Any]] | None", _json_safe(tool_calls)),
                        tokens_used=tokens_used,
                        finished_at=datetime.now(UTC),
                    ),
                )
                await db.commit()

            yield _sse_event(
                {
                    "type": "completed",
                    "text": final_text,
                    "task_id": task_id,
                    "agentic_run_id": agentic_run_id,
                    "tokens_used": tokens_used,
                }
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Agentic task %s failed: %s\n%s", task_id, error_msg, traceback.format_exc()
            )

            # Update DB with failed status
            try:
                async with get_async_session_context() as db:
                    await update_agentic_task(
                        db,
                        task_id,
                        AgenticTaskUpdate(
                            status="failed",
                            error_message=error_msg,
                            result={"response": f"Error: {error_msg}"},
                            messages=cast("list[dict[str, Any]] | None", _json_safe(messages)),
                            tool_calls=cast("list[dict[str, Any]] | None", _json_safe(tool_calls)),
                            finished_at=datetime.now(UTC),
                        ),
                    )
                    await db.commit()
            except Exception:
                logger.exception("Failed to update task %s status to failed", task_id)

            yield _sse_event({"type": "error", "message": error_msg, "task_id": task_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
