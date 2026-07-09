"""Event publishing helpers for the dataset service.

Publishes events via EventBus (Valkey pub/sub) for async, decoupled consumers.
Falls back to a direct HTTP call to the notification service if EventBus fails.
"""

import logging
from typing import Any

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)


async def publish_dataset_created(
    dataset_id: str,
    dataset_slug: str,
    dataset_name: str,
    data_type: str,
    is_public: bool,
    created_by: str,
) -> None:
    """Publish a dataset.created event via EventBus + HTTP fallback."""
    print(f"[events] Publishing dataset.created for {dataset_slug}")

    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "dataset_slug": dataset_slug,
        "dataset_name": dataset_name,
        "data_type": data_type,
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
        await bus.publish("dataset.created", payload)
        await client.aclose()
        bus_ok = True
        print(f"[events] EventBus publish succeeded for dataset.created {dataset_slug}")
    except Exception as e:
        print(f"[events] EventBus publish failed: {e}")

    # 2. HTTP fallback — only if EventBus failed
    if not bus_ok:
        try:
            settings = get_settings()
            url = (
                f"{settings.notification_service_url}"
                f"{settings.api_v1_prefix}/notifications/internal/notify"
            )
            print(f"[events] HTTP fallback → POST {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "resource_type": "dataset",
                        "resource_id": dataset_id,
                        "title": f"[Dataset] New dataset: {dataset_name}",
                        "message": (
                            f"[Dataset] Dataset '{dataset_name}' ({data_type}) has been created."
                        ),
                        "link": f"/datasets/{dataset_id}",
                        "category": "dataset_created",
                        "source_type": "dataset",
                        "source_id": dataset_id,
                    },
                )
                if resp.status_code == 201:
                    print(f"[events] HTTP notify succeeded: {resp.json()}")
                else:
                    print(f"[events] HTTP notify returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[events] HTTP fallback failed: {e}")


async def publish_dataset_transfer_requested(
    dataset_id: str,
    dataset_slug: str,
    dataset_name: str,
    version: int,
    source_bucket_id: str,
    file_count: int,
) -> None:
    """Publish a dataset.transfer.requested event via EventBus + HTTP fallback."""
    print(f"[events] Publishing dataset.transfer.requested for {dataset_slug} v{version}")

    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "dataset_slug": dataset_slug,
        "dataset_name": dataset_name,
        "version": version,
        "source_bucket_id": source_bucket_id,
        "file_count": file_count,
    }

    bus_ok = False
    try:
        import valkey.asyncio as valkey_async

        from core.events import EventBus

        settings = get_settings()
        client = valkey_async.from_url(settings.valkey_url)
        bus = EventBus(client)
        await bus.publish("dataset.transfer.requested", payload)
        await client.aclose()
        bus_ok = True
        print(
            f"[events] EventBus publish succeeded for "
            f"dataset.transfer.requested {dataset_slug} v{version}"
        )
    except Exception as e:
        print(f"[events] EventBus publish failed: {e}")

    if not bus_ok:
        try:
            settings = get_settings()
            url = (
                f"{settings.notification_service_url}"
                f"{settings.api_v1_prefix}/notifications/internal/notify"
            )
            print(f"[events] HTTP fallback → POST {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "resource_type": "dataset",
                        "resource_id": dataset_id,
                        "title": f"[Dataset] Transfer requested: {dataset_name} v{version}",
                        "message": (
                            f"[Dataset] Transfer of {file_count} file(s) from bucket "
                            f"{source_bucket_id} requested for '{dataset_name}' v{version}."
                        ),
                        "link": f"/datasets/{dataset_id}",
                        "category": "dataset_update",
                        "source_type": "dataset",
                        "source_id": dataset_id,
                    },
                )
                if resp.status_code == 201:
                    print(f"[events] HTTP notify succeeded: {resp.json()}")
                else:
                    print(f"[events] HTTP notify returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[events] HTTP fallback failed: {e}")


async def publish_dataset_version_uploaded(
    dataset_id: str,
    dataset_slug: str,
    dataset_name: str,
    version: int,
    file_name: str,
    file_size: int,
) -> None:
    """Publish a dataset.version.uploaded event via EventBus + HTTP fallback."""
    print(f"[events] Publishing dataset.version.uploaded for {dataset_slug} v{version}")

    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "dataset_slug": dataset_slug,
        "dataset_name": dataset_name,
        "version": version,
        "file_name": file_name,
        "file_size": file_size,
    }

    # 1. EventBus (preferred path)
    bus_ok = False
    try:
        import valkey.asyncio as valkey_async

        from core.events import EventBus

        settings = get_settings()
        client = valkey_async.from_url(settings.valkey_url)
        bus = EventBus(client)
        await bus.publish("dataset.version.uploaded", payload)
        await client.aclose()
        bus_ok = True
        print(
            f"[events] EventBus publish succeeded for "
            f"dataset.version.uploaded {dataset_slug} v{version}"
        )
    except Exception as e:
        print(f"[events] EventBus publish failed: {e}")

    # 2. HTTP fallback — only if EventBus failed
    if not bus_ok:
        try:
            settings = get_settings()
            url = (
                f"{settings.notification_service_url}"
                f"{settings.api_v1_prefix}/notifications/internal/notify"
            )
            print(f"[events] HTTP fallback → POST {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "resource_type": "dataset",
                        "resource_id": dataset_id,
                        "title": f"[Dataset] {dataset_name} v{version} uploaded",
                        "message": f"[Dataset] Version {version} of '{dataset_name}' has been uploaded ({file_name}).",
                        "link": f"/datasets/{dataset_id}",
                        "category": "dataset_update",
                        "source_type": "dataset",
                        "source_id": dataset_id,
                    },
                )
                if resp.status_code == 201:
                    print(f"[events] HTTP notify succeeded: {resp.json()}")
                else:
                    print(f"[events] HTTP notify returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[events] HTTP fallback failed: {e}")
