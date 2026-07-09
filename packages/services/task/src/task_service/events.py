"""Event publishing helpers for the task service.

Publishes events via EventBus (Valkey pub/sub) for async, decoupled
consumers. Falls back to a direct HTTP call to the notification service if
EventBus fails.

Replaces the old ``publish_task_run_*`` helpers in tool-service. The bug
in those (references to an undefined ``assignment_id`` in the HTTP
fallback payloads) is fixed here — every fallback uses ``task_run_id``.
"""

import logging
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


async def _publish(channel: str, payload: dict[str, Any], fallback_notify: dict[str, Any]) -> None:
    """Publish an event via EventBus, falling back to HTTP POST."""
    logger.info("[task-events] Publishing %s: %s", channel, payload)

    bus_ok = False
    try:
        import valkey.asyncio as valkey_async

        from core.events import EventBus

        settings = get_settings()
        client = valkey_async.from_url(settings.valkey_url)
        bus = EventBus(client)
        await bus.publish(channel, payload)
        await client.aclose()
        bus_ok = True
        logger.info("[task-events] EventBus publish succeeded for %s", channel)
    except Exception as e:
        logger.warning("[task-events] EventBus publish failed: %s", e)

    if not bus_ok:
        try:
            settings = get_settings()
            url = (
                f"{settings.notification_service_url}{settings.api_v1_prefix}"
                "/notifications/internal/notify"
            )
            logger.info("[task-events] HTTP fallback → POST %s", url)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=fallback_notify)
                if resp.status_code == 201:
                    logger.info("[task-events] HTTP notify succeeded")
                else:
                    logger.warning(
                        "[task-events] HTTP notify returned %s: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except Exception as e:
            logger.warning("[task-events] HTTP fallback failed: %s", e)


def _notify_payload(
    task_run_id: str, headline: str, message: str, link: str = ""
) -> dict[str, Any]:
    return {
        "resource_type": "task_run",
        "resource_id": task_run_id,
        "title": headline,
        "message": message,
        "link": link or f"/task-runs/{task_run_id}",
        "category": "task_run",
        "source_type": "task_run",
        "source_id": task_run_id,
    }


async def publish_task_run_created(
    task_run_id: str,
    tool_version_id: str,
    tool_name: str,
    assigned_user_id: str | None = None,
    assigned_team_slug: str | None = None,
    project_lead_id: str | None = None,
    created_by: str = "",
) -> None:
    payload = {
        "task_run_id": task_run_id,
        "tool_version_id": tool_version_id,
        "tool_name": tool_name,
        "assigned_user_id": assigned_user_id,
        "assigned_team_slug": assigned_team_slug,
        "project_lead_id": project_lead_id,
        "created_by": created_by,
    }
    await _publish(
        "human.task_run.created",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] {tool_name}",
            f"A new task run has been created from tool '{tool_name}'.",
        ),
    )


async def publish_task_run_accepted(
    task_run_id: str, tool_name: str, accepted_by: str = ""
) -> None:
    payload = {"task_run_id": task_run_id, "tool_name": tool_name, "accepted_by": accepted_by}
    await _publish(
        "human.task_run.accepted",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] Accepted — {tool_name}",
            f"Task run '{tool_name}' has been accepted.",
        ),
    )


async def publish_task_run_submitted(
    task_run_id: str, tool_name: str, submitted_by: str = ""
) -> None:
    payload = {
        "task_run_id": task_run_id,
        "tool_name": tool_name,
        "submitted_by": submitted_by,
    }
    await _publish(
        "human.task_run.submitted",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] Submitted — {tool_name}",
            f"Task run '{tool_name}' has been completed and submitted.",
        ),
    )


async def publish_task_run_declined(
    task_run_id: str, tool_name: str, declined_by: str = ""
) -> None:
    payload = {"task_run_id": task_run_id, "tool_name": tool_name, "declined_by": declined_by}
    await _publish(
        "human.task_run.declined",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] Declined — {tool_name}",
            f"Task run '{tool_name}' has been declined.",
        ),
    )


async def publish_task_run_delegated(
    task_run_id: str,
    tool_name: str,
    delegated_from: str = "",
    delegated_to: str = "",
) -> None:
    payload = {
        "task_run_id": task_run_id,
        "tool_name": tool_name,
        "delegated_from": delegated_from,
        "delegated_to": delegated_to,
    }
    await _publish(
        "human.task_run.delegated",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] Delegated — {tool_name}",
            f"Task run '{tool_name}' has been delegated.",
        ),
    )


async def publish_task_run_escalated(
    task_run_id: str, tool_name: str, escalated_to: str = ""
) -> None:
    payload = {"task_run_id": task_run_id, "tool_name": tool_name, "escalated_to": escalated_to}
    await _publish(
        "human.task_run.escalated",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] Escalated — {tool_name}",
            f"Task run '{tool_name}' has been escalated.",
        ),
    )


async def publish_task_run_updated(task_run_id: str, tool_name: str, actor: str = "") -> None:
    payload = {"task_run_id": task_run_id, "tool_name": tool_name, "actor": actor}
    await _publish(
        "human.task_run.updated",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] Update — {tool_name}",
            f"A new update was posted on task run '{tool_name}'.",
        ),
    )


async def publish_task_run_cancelled(task_run_id: str, tool_name: str) -> None:
    payload = {"task_run_id": task_run_id, "tool_name": tool_name}
    await _publish(
        "human.task_run.cancelled",
        payload,
        _notify_payload(
            task_run_id,
            f"[Task Run] Cancelled — {tool_name}",
            f"Task run '{tool_name}' has been cancelled.",
        ),
    )
