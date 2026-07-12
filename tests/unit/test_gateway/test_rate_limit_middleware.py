"""Tests for the gateway rate limiting middleware."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.middleware.rate_limit import RateLimitMiddleware


@pytest.fixture
def app():
    _app = FastAPI()
    _app.add_middleware(RateLimitMiddleware, max_requests=5, window_seconds=60)

    @_app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestRateLimiting:
    @patch("gateway.middleware.rate_limit.get_valkey_client")
    def test_allowed_request_passes(self, mock_get_client, client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        with patch("gateway.middleware.rate_limit.RateLimiter") as MockLimiter:
            limiter_instance = AsyncMock()
            limiter_instance.is_allowed = AsyncMock(return_value=(True, 4))
            MockLimiter.return_value = limiter_instance

            resp = client.get("/test")
            assert resp.status_code == 200
            assert resp.headers["x-ratelimit-limit"] == "5"
            assert resp.headers["x-ratelimit-remaining"] == "4"

    @patch("gateway.middleware.rate_limit.get_valkey_client")
    def test_rate_limited_returns_429(self, mock_get_client, client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        with patch("gateway.middleware.rate_limit.RateLimiter") as MockLimiter:
            limiter_instance = AsyncMock()
            limiter_instance.is_allowed = AsyncMock(return_value=(False, 0))
            MockLimiter.return_value = limiter_instance

            resp = client.get("/test")
            assert resp.status_code == 429
            assert "Rate limit exceeded" in resp.json()["detail"]
            assert resp.headers["x-ratelimit-limit"] == "5"
            assert resp.headers["x-ratelimit-remaining"] == "0"
            assert resp.headers["retry-after"] == "60"

    @patch("gateway.middleware.rate_limit.get_valkey_client")
    def test_fail_open_on_exception(self, mock_get_client, client):
        """When Valkey is down, requests should pass through."""
        mock_get_client.side_effect = Exception("Valkey connection refused")

        resp = client.get("/test")
        assert resp.status_code == 200

    @patch("gateway.middleware.rate_limit.get_valkey_client")
    def test_uses_ip_for_unauthenticated(self, mock_get_client, client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        with patch("gateway.middleware.rate_limit.RateLimiter") as MockLimiter:
            limiter_instance = AsyncMock()
            limiter_instance.is_allowed = AsyncMock(return_value=(True, 3))
            MockLimiter.return_value = limiter_instance

            client.get("/test")
            # Check it was called with ip-based key
            call_args = limiter_instance.is_allowed.call_args[0][0]
            assert call_args.startswith("ip:")
