"""Tests for the EventBus (Valkey pub/sub abstraction)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.events import EventBus


@pytest.fixture
def mock_valkey():
    client = AsyncMock()
    pubsub = AsyncMock()
    client.pubsub = MagicMock(return_value=pubsub)
    return client


@pytest.fixture
def event_bus(mock_valkey):
    return EventBus(mock_valkey, prefix="test:events")


class TestEventBusPublish:
    async def test_publish_serializes_and_sends(self, event_bus, mock_valkey):
        await event_bus.publish("tool.created", {"id": "t1", "name": "rdkit"})

        mock_valkey.publish.assert_called_once()
        channel, message = mock_valkey.publish.call_args[0]
        assert channel == "test:events:tool.created"
        data = json.loads(message)
        assert data["type"] == "tool.created"
        assert data["payload"] == {"id": "t1", "name": "rdkit"}

    async def test_publish_different_event_types(self, event_bus, mock_valkey):
        await event_bus.publish("pipeline.started", {"run_id": "r1"})
        await event_bus.publish("pipeline.completed", {"run_id": "r1"})

        assert mock_valkey.publish.call_count == 2
        calls = mock_valkey.publish.call_args_list
        assert "test:events:pipeline.started" in calls[0][0]
        assert "test:events:pipeline.completed" in calls[1][0]


class TestEventBusSubscribe:
    async def test_subscribe_registers_channel(self, event_bus):
        pubsub = event_bus._pubsub
        # Make get_message return None then raise to break loop
        from valkey.exceptions import ConnectionError as ValkeyConnectionError

        pubsub.get_message = AsyncMock(side_effect=[None, ValkeyConnectionError("done")])

        handler = AsyncMock()
        with pytest.raises(ValkeyConnectionError):
            await event_bus.subscribe("tool.created", handler)

        pubsub.subscribe.assert_called_once_with("test:events:tool.created")

    async def test_subscribe_dispatches_message(self, event_bus):
        pubsub = event_bus._pubsub
        from valkey.exceptions import ConnectionError as ValkeyConnectionError

        message = {
            "type": "message",
            "data": json.dumps({"type": "tool.created", "payload": {"id": "t1"}}),
        }
        pubsub.get_message = AsyncMock(side_effect=[message, ValkeyConnectionError("stop")])

        handler = AsyncMock()
        with pytest.raises(ValkeyConnectionError):
            await event_bus.subscribe("tool.created", handler)

        handler.assert_called_once_with({"id": "t1"})

    async def test_subscribe_ignores_timeout(self, event_bus):
        """ValkeyTimeoutError should be handled gracefully (continue loop)."""
        pubsub = event_bus._pubsub
        from valkey.exceptions import ConnectionError as ValkeyConnectionError
        from valkey.exceptions import TimeoutError as ValkeyTimeoutError

        pubsub.get_message = AsyncMock(
            side_effect=[ValkeyTimeoutError("idle"), ValkeyConnectionError("stop")]
        )

        handler = AsyncMock()
        with pytest.raises(ValkeyConnectionError):
            await event_bus.subscribe("x", handler)

        handler.assert_not_called()


class TestEventBusClose:
    async def test_close_unsubscribes_and_closes(self, event_bus):
        pubsub = event_bus._pubsub
        await event_bus.close()
        pubsub.unsubscribe.assert_called_once()
        pubsub.aclose.assert_called_once()


class TestEventBusChannelNaming:
    def test_channel_format(self, event_bus):
        assert event_bus._channel("foo.bar") == "test:events:foo.bar"

    def test_default_prefix(self, mock_valkey):
        bus = EventBus(mock_valkey)
        assert bus._channel("x") == "techneos:events:x"
