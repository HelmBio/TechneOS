"""Event publishing helpers for the agent service.

Publishes events via EventBus (Valkey pub/sub) for async, decoupled consumers.
Falls back to a direct HTTP call to the notification service if EventBus fails.
"""

import logging
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


async def publish_agent_created(
    agent_id: str,
    agent_slug: str,
    agent_name: str,
    is_public: bool,
    created_by: str,
) -> None:
    """Publish an agent.created event via EventBus + HTTP fallback."""
    logger.info("[events] Publishing agent.created for %s", agent_slug)

    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_slug": agent_slug,
        "agent_name": agent_name,
        "is_public": is_public,
        "created_by": created_by,
    }

    # 1. EventBus (preferred path)
    bus_ok = False
    try:
        import valkey.asyncio as valkey_async

        from core.events import EventBus

        settings = get_settings()
        client = valkey_async.from_url(settings.valkey_url)
        bus = EventBus(client)
        await bus.publish("agent.created", payload)
        await client.aclose()
        bus_ok = True
        logger.info("[events] EventBus publish succeeded for agent.created %s", agent_slug)
    except Exception as e:
        logger.warning("[events] EventBus publish failed: %s", e)

    # 2. HTTP fallback — only if EventBus failed
    if not bus_ok:
        try:
            settings = get_settings()
            url = (
                f"{settings.notification_service_url}"
                f"{settings.api_v1_prefix}/notifications/internal/notify"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "resource_type": "agent",
                        "resource_id": agent_id,
                        "title": f"[Agent] New agent: {agent_name}",
                        "message": f"[Agent] Agent '{agent_name}' has been created.",
                        "link": f"/agents/{agent_id}",
                        "category": "agent_created",
                        "source_type": "agent",
                        "source_id": agent_id,
                    },
                )
                if resp.status_code == 201:
                    logger.info("[events] HTTP notify succeeded: %s", resp.json())
                else:
                    logger.warning(
                        "[events] HTTP notify returned %d: %s", resp.status_code, resp.text
                    )
        except Exception as e:
            logger.warning("[events] HTTP fallback failed: %s", e)


async def publish_agent_updated(
    agent_id: str,
    agent_slug: str,
    agent_name: str,
) -> None:
    """Publish an agent.updated event via EventBus + HTTP fallback."""
    logger.info("[events] Publishing agent.updated for %s", agent_slug)

    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_slug": agent_slug,
        "agent_name": agent_name,
    }

    # 1. EventBus (preferred path)
    bus_ok = False
    try:
        import valkey.asyncio as valkey_async

        from core.events import EventBus

        settings = get_settings()
        client = valkey_async.from_url(settings.valkey_url)
        bus = EventBus(client)
        await bus.publish("agent.updated", payload)
        await client.aclose()
        bus_ok = True
        logger.info("[events] EventBus publish succeeded for agent.updated %s", agent_slug)
    except Exception as e:
        logger.warning("[events] EventBus publish failed: %s", e)

    # 2. HTTP fallback — only if EventBus failed
    if not bus_ok:
        try:
            settings = get_settings()
            url = (
                f"{settings.notification_service_url}"
                f"{settings.api_v1_prefix}/notifications/internal/notify"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "resource_type": "agent",
                        "resource_id": agent_id,
                        "title": f"[Agent] {agent_name} updated",
                        "message": f"[Agent] Agent '{agent_name}' has been updated.",
                        "link": f"/agents/{agent_id}",
                        "category": "agent_update",
                        "source_type": "agent",
                        "source_id": agent_id,
                    },
                )
                if resp.status_code == 201:
                    logger.info("[events] HTTP notify succeeded: %s", resp.json())
                else:
                    logger.warning(
                        "[events] HTTP notify returned %d: %s", resp.status_code, resp.text
                    )
        except Exception as e:
            logger.warning("[events] HTTP fallback failed: %s", e)
