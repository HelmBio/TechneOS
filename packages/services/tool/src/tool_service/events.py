"""Event publishing helpers for the tool service.

Publishes events via EventBus (Valkey pub/sub) for async, decoupled consumers.
Falls back to a direct HTTP call to the notification service if EventBus fails.
"""

import logging
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


async def _publish(channel: str, payload: dict[str, Any], fallback_notify: dict[str, Any]) -> None:
    """Publish an event via EventBus, falling back to HTTP POST."""
    logger.info("[events] Publishing %s: %s", channel, payload)

    # 1. EventBus (preferred path)
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
        logger.info("[events] EventBus publish succeeded for %s", channel)
    except Exception as e:
        logger.warning("[events] EventBus publish failed: %s", e)

    # 2. HTTP fallback — only if EventBus failed
    if not bus_ok:
        try:
            settings = get_settings()
            url = f"{settings.notification_service_url}{settings.api_v1_prefix}/notifications/internal/notify"
            logger.info("[events] HTTP fallback → POST %s", url)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=fallback_notify)
                if resp.status_code == 201:
                    logger.info("[events] HTTP notify succeeded")
                else:
                    logger.warning(
                        "[events] HTTP notify returned %s: %s", resp.status_code, resp.text[:200]
                    )
        except Exception as e:
            logger.warning("[events] HTTP fallback failed: %s", e)


async def publish_tool_created(
    tool_id: str,
    tool_slug: str,
    tool_name: str,
) -> None:
    """Publish a tool.created event."""
    payload = {
        "tool_id": tool_id,
        "tool_slug": tool_slug,
        "tool_name": tool_name,
    }
    await _publish(
        "tool.created",
        payload,
        {
            "resource_type": "tool",
            "resource_id": tool_id,
            "title": f"[Tool] {tool_name} registered",
            "message": f"New tool '{tool_name}' ({tool_slug}) has been registered.",
            "link": f"/tools/{tool_id}",
            "category": "tool_update",
            "source_type": "tool",
            "source_id": tool_id,
        },
    )


async def publish_tool_version_deleted(
    tool_id: str,
    tool_slug: str,
    tool_name: str,
    version: int,
) -> None:
    """Publish a tool.version.deleted event."""
    payload = {
        "tool_id": tool_id,
        "tool_slug": tool_slug,
        "tool_name": tool_name,
        "version": version,
    }
    await _publish(
        "tool.version.deleted",
        payload,
        {
            "resource_type": "tool",
            "resource_id": tool_id,
            "title": f"[Tool] {tool_name} v{version} removed",
            "message": f"Version {version} of '{tool_name}' has been deleted.",
            "link": f"/tools/{tool_id}",
            "category": "tool_update",
            "source_type": "tool",
            "source_id": tool_id,
        },
    )


async def publish_tool_run_completed(
    run_id: str,
    tool_id: str,
    tool_name: str,
    submitted_by: str = "",
) -> None:
    """Publish a tool.run.completed event."""
    payload = {
        "run_id": run_id,
        "tool_id": tool_id,
        "tool_name": tool_name,
        "submitted_by": submitted_by,
    }
    await _publish(
        "tool.run.completed",
        payload,
        {
            "resource_type": "tool_run",
            "resource_id": run_id,
            "title": f"[Tool Run] Run completed — {tool_name}",
            "message": f"[Tool Run] {tool_name} run {run_id[:8]} completed successfully.",
            "link": f"/tool-runs/{run_id}",
            "category": "tool_run",
            "source_type": "tool",
            "source_id": tool_id,
        },
    )


async def publish_tool_run_failed(
    run_id: str,
    tool_id: str,
    tool_name: str,
    submitted_by: str = "",
    error: str | None = None,
) -> None:
    """Publish a tool.run.failed event."""
    payload = {
        "run_id": run_id,
        "tool_id": tool_id,
        "tool_name": tool_name,
        "submitted_by": submitted_by,
        "error": error or "",
    }
    await _publish(
        "tool.run.failed",
        payload,
        {
            "resource_type": "tool_run",
            "resource_id": run_id,
            "title": f"[Tool Run] Run failed — {tool_name}",
            "message": error or f"[Tool Run] {tool_name} run {run_id[:8]} failed.",
            "link": f"/tool-runs/{run_id}",
            "category": "tool_run",
            "source_type": "tool",
            "source_id": tool_id,
        },
    )


# Human task-run events moved to task-service (see packages/services/task/src/task_service/events.py).


async def publish_tool_version_active(
    tool_id: str,
    tool_slug: str,
    tool_name: str,
    version: int,
) -> None:
    """Publish a tool.version.active event."""
    payload = {
        "tool_id": tool_id,
        "tool_slug": tool_slug,
        "tool_name": tool_name,
        "version": version,
    }
    await _publish(
        "tool.version.active",
        payload,
        {
            "resource_type": "tool",
            "resource_id": tool_id,
            "title": f"[Tool] {tool_name} v{version} is now available",
            "message": f"A new version of {tool_name} has been activated.",
            "link": f"/tools/{tool_id}",
            "category": "tool_update",
            "source_type": "tool",
            "source_id": tool_id,
        },
    )
