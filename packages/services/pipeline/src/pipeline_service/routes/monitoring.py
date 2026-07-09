"""Real-time pipeline run monitoring via Server-Sent Events (SSE).

Provides an ``/runs/{run_id}/events`` endpoint that streams status
updates for a pipeline run and its steps.  The stream polls Airflow
at a configurable interval and emits JSON events whenever the run or
step statuses change.

Event format (each line prefixed with ``data: ``)::

    {
        "type": "run_status",          // or "step_status"
        "run_id": "...",
        "status": "running",
        "step_name": "dock_vina",      // only for step_status
        "timestamp": "2025-01-15T..."
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.scope import check_resource_access
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from pipeline_service.crud.runs import get_run, get_step_runs
from pipeline_service.orchestrator import sync_run_status

logger = logging.getLogger(__name__)

router = APIRouter()

# How often (seconds) the SSE stream polls for updates
_SSE_POLL_INTERVAL = 5
# Maximum duration (seconds) for a single SSE connection
_SSE_MAX_DURATION = 3600


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    """Stream real-time status events for a pipeline run via SSE.

    The connection remains open, emitting events as the run progresses.
    It closes automatically when the run reaches a terminal state
    (completed, failed, cancelled) or when ``_SSE_MAX_DURATION`` is
    exceeded.
    """
    run = await get_run(session, run_id)
    check_resource_access(current_user, run, resource_name="pipeline-run")

    return StreamingResponse(
        _event_generator(session, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_generator(
    session: AsyncSession,
    run_id: str,
) -> Any:
    """Async generator that yields SSE-formatted events."""
    terminal_states = {"completed", "failed", "cancelled"}
    last_run_status: str | None = None
    last_step_statuses: dict[str, str] = {}
    elapsed = 0

    while elapsed < _SSE_MAX_DURATION:
        try:
            # Expire cached objects so we read fresh data from the DB.
            # Without this, the session's identity map returns stale
            # step statuses that were cached on a previous iteration.
            session.expire_all()

            # Sync from Airflow and read current state
            run = await get_run(session, run_id)
            run = await sync_run_status(session, run)
            steps = await get_step_runs(session, run_id)

            # Emit run status if changed
            if run.status != last_run_status:
                last_run_status = run.status
                event = {
                    "type": "run_status",
                    "run_id": run_id,
                    "status": run.status,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "error_message": run.error_message,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                yield _format_sse(event, event_type="run_status")

            # Emit step status changes
            for step in steps:
                prev = last_step_statuses.get(step.step_name)
                if step.status != prev:
                    last_step_statuses[step.step_name] = step.status
                    event = {
                        "type": "step_status",
                        "run_id": run_id,
                        "step_name": step.step_name,
                        "status": step.status,
                        "started_at": step.started_at.isoformat() if step.started_at else None,
                        "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                        "error_message": step.error_message,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    yield _format_sse(event, event_type="step_status")

            # Stop if terminal
            if run.status in terminal_states:
                yield _format_sse(
                    {"type": "stream_end", "run_id": run_id, "final_status": run.status},
                    event_type="stream_end",
                )
                return

        except Exception:
            logger.exception("SSE poll error for run %s", run_id)
            yield _format_sse(
                {"type": "error", "message": "Internal polling error"},
                event_type="error",
            )

        # Heartbeat to keep the connection alive
        yield ": heartbeat\n\n"

        await asyncio.sleep(_SSE_POLL_INTERVAL)
        elapsed += _SSE_POLL_INTERVAL

    # Timeout
    yield _format_sse(
        {"type": "stream_end", "run_id": run_id, "reason": "timeout"},
        event_type="stream_end",
    )


def _format_sse(data: dict[str, Any], event_type: str = "message") -> str:
    """Format a dict as an SSE event string."""
    payload = json.dumps(data)
    return f"event: {event_type}\ndata: {payload}\n\n"
