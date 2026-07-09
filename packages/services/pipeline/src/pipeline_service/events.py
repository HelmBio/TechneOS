"""Event publishing helpers for the pipeline service.

Publishes events via EventBus (Valkey pub/sub) for async, decoupled consumers.
Falls back to a direct HTTP call to the notification service if EventBus fails.
"""

import logging
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


async def _publish(channel: str, payload: dict[str, Any], fallback_notify: dict[str, Any]) -> None:
    """Publish an event to EventBus with HTTP fallback."""
    print(f"[events] Publishing {channel}")

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
        print(f"[events] EventBus publish succeeded for {channel}")
    except Exception as e:
        print(f"[events] EventBus publish failed: {e}")

    # 2. HTTP fallback — only if EventBus failed
    if not bus_ok:
        try:
            settings = get_settings()
            url = f"{settings.notification_service_url}{settings.api_v1_prefix}/notifications/internal/notify"
            print(f"[events] HTTP fallback → POST {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=fallback_notify)
                if resp.status_code == 201:
                    print(f"[events] HTTP notify succeeded: {resp.json()}")
                else:
                    print(f"[events] HTTP notify returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[events] HTTP fallback failed: {e}")


async def publish_pipeline_created(
    pipeline_id: str,
    pipeline_name: str,
    pipeline_slug: str,
    org_id: str,
    user_id: str,
) -> None:
    """Publish a pipeline.created event."""
    payload = {
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "pipeline_slug": pipeline_slug,
        "org_id": org_id,
        "user_id": user_id,
    }
    await _publish(
        "pipeline.created",
        payload,
        {
            "resource_type": "pipeline",
            "resource_id": pipeline_id,
            "title": f"[Pipeline] Pipeline '{pipeline_name}' created",
            "message": f"[Pipeline] A new pipeline '{pipeline_name}' has been created.",
            "link": f"/pipelines/{pipeline_id}",
            "category": "pipeline_update",
            "source_type": "pipeline",
            "source_id": pipeline_id,
        },
    )


async def publish_pipeline_updated(
    pipeline_id: str,
    pipeline_name: str,
    version: int,
) -> None:
    """Publish a pipeline.updated event."""
    payload = {
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "version": version,
    }
    await _publish(
        "pipeline.updated",
        payload,
        {
            "resource_type": "pipeline",
            "resource_id": pipeline_id,
            "title": f"[Pipeline] Pipeline '{pipeline_name}' updated (v{version})",
            "message": f"[Pipeline] Pipeline '{pipeline_name}' has been updated to version {version}.",
            "link": f"/pipelines/{pipeline_id}",
            "category": "pipeline_update",
            "source_type": "pipeline",
            "source_id": pipeline_id,
        },
    )


async def publish_pipeline_version_created(
    pipeline_id: str,
    pipeline_name: str,
    pipeline_slug: str,
    version: int,
    changelog: str | None = None,
) -> None:
    """Publish a pipeline.version.created event."""
    payload = {
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "pipeline_slug": pipeline_slug,
        "version": version,
        "changelog": changelog or "",
    }
    await _publish(
        "pipeline.version.created",
        payload,
        {
            "resource_type": "pipeline",
            "resource_id": pipeline_id,
            "title": f"[Pipeline] {pipeline_name} v{version} created",
            "message": changelog
            or f"[Pipeline] Version {version} of '{pipeline_name}' has been created.",
            "link": f"/pipelines/{pipeline_id}",
            "category": "pipeline_update",
            "source_type": "pipeline",
            "source_id": pipeline_id,
        },
    )


async def publish_pipeline_run_completed(
    run_id: str,
    pipeline_id: str,
    pipeline_name: str,
    submitted_by: str = "",
) -> None:
    """Publish a pipeline.run.completed event."""
    payload = {
        "run_id": run_id,
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "submitted_by": submitted_by,
    }
    await _publish(
        "pipeline.run.completed",
        payload,
        {
            "resource_type": "pipeline_run",
            "resource_id": run_id,
            "title": f"[Run] Run completed — {pipeline_name}",
            "message": f"[Run] Pipeline '{pipeline_name}' run {run_id[:8]} completed successfully.",
            "link": f"/pipeline-runs/{run_id}",
            "category": "pipeline_run",
            "source_type": "pipeline",
            "source_id": pipeline_id,
        },
    )


async def publish_pipeline_run_failed(
    run_id: str,
    pipeline_id: str,
    pipeline_name: str,
    submitted_by: str = "",
    error: str | None = None,
) -> None:
    """Publish a pipeline.run.failed event."""
    payload = {
        "run_id": run_id,
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "submitted_by": submitted_by,
        "error": error or "",
    }
    await _publish(
        "pipeline.run.failed",
        payload,
        {
            "resource_type": "pipeline_run",
            "resource_id": run_id,
            "title": f"[Run] Run failed — {pipeline_name}",
            "message": error or f"[Run] Pipeline '{pipeline_name}' run {run_id[:8]} failed.",
            "link": f"/pipeline-runs/{run_id}",
            "category": "pipeline_run",
            "source_type": "pipeline",
            "source_id": pipeline_id,
        },
    )
