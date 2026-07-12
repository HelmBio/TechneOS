"""Tests for the gateway proxy routes."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.routes.proxy import SERVICE_ROUTES, _is_sse_request, router


@pytest.fixture(autouse=True)
def clear_routes():
    """Clear cached routes between tests."""
    SERVICE_ROUTES.clear()
    yield
    SERVICE_ROUTES.clear()


@pytest.fixture
def app():
    from fastapi import FastAPI

    _app = FastAPI()
    _app.include_router(router, prefix="/api/v1")
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestIsSSERequest:
    def test_accept_text_event_stream(self):
        request = MagicMock()
        request.headers = {"accept": "text/event-stream"}
        assert _is_sse_request(request, "/agents/123/run") is True

    def test_path_ends_with_stream(self):
        request = MagicMock()
        request.headers = {"accept": "application/json"}
        assert _is_sse_request(request, "/agents/123/stream") is True

    def test_normal_request(self):
        request = MagicMock()
        request.headers = {"accept": "application/json"}
        assert _is_sse_request(request, "/tools") is False


class TestProxyRouting:
    @patch("gateway.routes.proxy.get_settings")
    def test_no_matching_service_returns_404(self, mock_settings, client):
        settings = MagicMock()
        settings.api_v1_prefix = "/api/v1"
        settings.auth_service_url = "http://auth:8000"
        settings.dataset_service_url = "http://dataset:8000"
        settings.tool_service_url = "http://tool:8000"
        settings.pipeline_service_url = "http://pipeline:8000"
        settings.agent_service_url = "http://agent:8000"
        settings.notification_service_url = "http://notification:8000"
        mock_settings.return_value = settings

        resp = client.get("/api/v1/nonexistent-path-xyz")
        assert resp.status_code == 404
        assert "No service found" in resp.json()["detail"]

    @patch("gateway.routes.proxy._proxy_buffered")
    @patch("gateway.routes.proxy.get_settings")
    def test_tools_route_matched(self, mock_settings, mock_proxy, client):
        settings = MagicMock()
        settings.api_v1_prefix = "/api/v1"
        settings.auth_service_url = "http://auth:8000"
        settings.dataset_service_url = "http://dataset:8000"
        settings.tool_service_url = "http://tool:8000"
        settings.pipeline_service_url = "http://pipeline:8000"
        settings.agent_service_url = "http://agent:8000"
        settings.notification_service_url = "http://notification:8000"
        mock_settings.return_value = settings

        from fastapi.responses import JSONResponse

        mock_proxy.return_value = JSONResponse({"proxied": True})

        resp = client.get("/api/v1/tools")
        assert resp.status_code == 200
        mock_proxy.assert_called_once()
        # Verify target URL contains tool service
        call_args = mock_proxy.call_args
        assert "tool:8000" in call_args[0][0]


class TestProxyBuffered:
    @patch("gateway.routes.proxy.get_settings")
    @patch("httpx.AsyncClient.request")
    def test_backend_unavailable_returns_503(self, mock_request, mock_settings, client):
        settings = MagicMock()
        settings.api_v1_prefix = "/api/v1"
        settings.auth_service_url = "http://auth:8000"
        settings.dataset_service_url = "http://dataset:8000"
        settings.tool_service_url = "http://tool:8000"
        settings.pipeline_service_url = "http://pipeline:8000"
        settings.agent_service_url = "http://agent:8000"
        settings.notification_service_url = "http://notification:8000"
        mock_settings.return_value = settings

        mock_request.side_effect = httpx.ConnectError("Connection refused")

        resp = client.get("/api/v1/tools")
        assert resp.status_code == 503
        assert "Backend service unavailable" in resp.json()["detail"]

    @patch("gateway.routes.proxy.get_settings")
    @patch("httpx.AsyncClient.request")
    def test_successful_proxy_returns_backend_response(self, mock_request, mock_settings, client):
        settings = MagicMock()
        settings.api_v1_prefix = "/api/v1"
        settings.auth_service_url = "http://auth:8000"
        settings.dataset_service_url = "http://dataset:8000"
        settings.tool_service_url = "http://tool:8000"
        settings.pipeline_service_url = "http://pipeline:8000"
        settings.agent_service_url = "http://agent:8000"
        settings.notification_service_url = "http://notification:8000"
        mock_settings.return_value = settings

        mock_resp = MagicMock()
        mock_resp.content = b'{"tools": []}'
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_request.return_value = mock_resp

        resp = client.get("/api/v1/tools")
        assert resp.status_code == 200
        assert resp.json() == {"tools": []}
