"""Tests for pipeline event publishing."""

from unittest.mock import AsyncMock, MagicMock, patch


class TestPublishHelper:
    """Test the internal _publish helper."""

    @patch("pipeline_service.events.httpx.AsyncClient")
    @patch("core.events.EventBus")
    @patch("valkey.asyncio.from_url")
    async def test_publish_eventbus_success(self, mock_from_url, mock_event_bus_cls, mock_httpx):
        from pipeline_service.events import _publish

        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_bus = AsyncMock()
        mock_event_bus_cls.return_value = mock_bus

        await _publish("test.ch", {"key": "val"}, {"fallback": "data"})

        mock_event_bus_cls.assert_called_once_with(mock_client)
        mock_bus.publish.assert_called_once_with("test.ch", {"key": "val"})
        mock_client.aclose.assert_called_once()
        mock_httpx.assert_not_called()

    @patch("pipeline_service.events.httpx.AsyncClient")
    @patch("core.events.EventBus")
    @patch("valkey.asyncio.from_url")
    async def test_publish_eventbus_fails_http_fallback(
        self, mock_from_url, mock_event_bus_cls, mock_httpx
    ):
        from pipeline_service.events import _publish

        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_bus = AsyncMock()
        mock_bus.publish.side_effect = Exception("Valkey down")
        mock_event_bus_cls.return_value = mock_bus

        mock_http_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "notif-1"}
        mock_http_client.__aenter__.return_value = mock_http_client
        mock_http_client.post.return_value = mock_response
        mock_httpx.return_value = mock_http_client

        await _publish("test.ch", {"key": "val"}, {"fallback": "data"})

        mock_bus.publish.assert_called_once()
        mock_httpx.assert_called_once()
        mock_http_client.post.assert_called_once()

    @patch("pipeline_service.events.httpx.AsyncClient")
    @patch("core.events.EventBus")
    @patch("valkey.asyncio.from_url")
    async def test_publish_both_fail(self, mock_from_url, mock_event_bus_cls, mock_httpx):
        from pipeline_service.events import _publish

        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_bus = AsyncMock()
        mock_bus.publish.side_effect = Exception("Valkey down")
        mock_event_bus_cls.return_value = mock_bus

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__.return_value = mock_http_client
        mock_http_client.post.side_effect = Exception("HTTP down")
        mock_httpx.return_value = mock_http_client

        await _publish("test.ch", {"key": "val"}, {"fallback": "data"})


class TestPublishFunctions:
    """Each typed publish function builds the correct payload."""

    @patch("pipeline_service.events._publish")
    async def test_publish_pipeline_created(self, mock_publish):
        from pipeline_service.events import publish_pipeline_created

        await publish_pipeline_created(
            pipeline_id="p-1",
            pipeline_name="Docking",
            pipeline_slug="docking",
            org_id="org-1",
            user_id="u-1",
        )
        channel, payload, fallback = mock_publish.call_args[0]
        assert channel == "pipeline.created"
        assert payload["pipeline_id"] == "p-1"
        assert payload["pipeline_name"] == "Docking"
        assert fallback["resource_type"] == "pipeline"

    @patch("pipeline_service.events._publish")
    async def test_publish_pipeline_updated(self, mock_publish):
        from pipeline_service.events import publish_pipeline_updated

        await publish_pipeline_updated(pipeline_id="p-1", pipeline_name="Docking", version=2)
        channel, payload, fallback = mock_publish.call_args[0]
        assert channel == "pipeline.updated"
        assert payload["version"] == 2
        assert "v2" in fallback["title"]

    @patch("pipeline_service.events._publish")
    async def test_publish_pipeline_version_created(self, mock_publish):
        from pipeline_service.events import publish_pipeline_version_created

        await publish_pipeline_version_created(
            pipeline_id="p-1",
            pipeline_name="Docking",
            pipeline_slug="docking",
            version=3,
            changelog="New step",
        )
        channel, payload, fallback = mock_publish.call_args[0]
        assert channel == "pipeline.version.created"
        assert payload["changelog"] == "New step"
        assert "v3" in fallback["title"]

    @patch("pipeline_service.events._publish")
    async def test_publish_pipeline_version_created_no_changelog(self, mock_publish):
        from pipeline_service.events import publish_pipeline_version_created

        await publish_pipeline_version_created(
            pipeline_id="p-1",
            pipeline_name="Docking",
            pipeline_slug="docking",
            version=3,
        )
        payload = mock_publish.call_args[0][1]
        assert payload["changelog"] == ""

    @patch("pipeline_service.events._publish")
    async def test_publish_pipeline_run_completed(self, mock_publish):
        from pipeline_service.events import publish_pipeline_run_completed

        await publish_pipeline_run_completed(
            run_id="r-1",
            pipeline_id="p-1",
            pipeline_name="Docking",
            submitted_by="u-1",
        )
        channel, payload, fallback = mock_publish.call_args[0]
        assert channel == "pipeline.run.completed"
        assert payload["run_id"] == "r-1"
        assert "completed" in fallback["title"].lower()

    @patch("pipeline_service.events._publish")
    async def test_publish_pipeline_run_failed(self, mock_publish):
        from pipeline_service.events import publish_pipeline_run_failed

        await publish_pipeline_run_failed(
            run_id="r-1",
            pipeline_id="p-1",
            pipeline_name="Docking",
            submitted_by="u-1",
            error="OOM",
        )
        channel, payload, fallback = mock_publish.call_args[0]
        assert channel == "pipeline.run.failed"
        assert payload["error"] == "OOM"
        assert "failed" in fallback["title"].lower()

    @patch("pipeline_service.events._publish")
    async def test_publish_pipeline_run_failed_no_error(self, mock_publish):
        from pipeline_service.events import publish_pipeline_run_failed

        await publish_pipeline_run_failed(
            run_id="r-1",
            pipeline_id="p-1",
            pipeline_name="Docking",
        )
        payload = mock_publish.call_args[0][1]
        assert payload["error"] == ""
