"""Tests for the auth service routes."""

import pytest

from auth_service.main import app


@pytest.fixture
def client():
    """Synchronous test client for basic route tests."""
    from fastapi.testclient import TestClient

    return TestClient(app)


class TestHealthEndpoint:
    """Test the health check endpoint."""

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "auth"
