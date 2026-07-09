"""Simple event bus backed by Valkey pub/sub.

Used for inter-service communication (e.g., pipeline status updates).
For Phase 1, this is a lightweight abstraction. In production, you might
use a proper message broker (RabbitMQ, NATS, etc.)
"""

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import valkey.asyncio as valkey_async
from valkey.exceptions import ConnectionError as ValkeyConnectionError
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

logger = logging.getLogger(__name__)


class EventBus:
    """Publish/subscribe event bus using Valkey."""

    def __init__(self, client: valkey_async.Valkey, prefix: str = "techneos:events") -> None:
        self._client = client
        self._prefix = prefix
        self._pubsub = client.pubsub()

    def _channel(self, event_type: str) -> str:
        return f"{self._prefix}:{event_type}"

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish an event."""
        message = json.dumps({"type": event_type, "payload": payload})
        await self._client.publish(self._channel(event_type), message)

    async def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Subscribe to an event type with an async handler.

        Handles idle timeouts gracefully by continuing the listen loop.
        Connection errors are re-raised so the caller can retry.
        """
        channel = self._channel(event_type)
        await self._pubsub.subscribe(channel)

        while True:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=30.0,
                )
                if message is not None and message["type"] == "message":
                    data = json.loads(message["data"])
                    await handler(data["payload"])
            except ValkeyTimeoutError:
                # Idle timeout — normal for long-lived pub/sub, just continue
                continue
            except ValkeyConnectionError:
                # Connection lost — re-raise so caller can reconnect
                raise

    async def close(self) -> None:
        """Close the pub/sub connection."""
        await self._pubsub.unsubscribe()
        await self._pubsub.aclose()
