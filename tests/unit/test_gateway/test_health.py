"""Tests for the gateway health endpoint."""

import pytest
from fastapi.testclient import TestClient

from gateway.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestGatewayHealth:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "gateway"
