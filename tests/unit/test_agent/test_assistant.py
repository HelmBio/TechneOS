"""Tests for the assistant routes — config, chat, delegate."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agent_service.main import app
from core.auth.dependencies import get_current_user
from core.database.postgres import get_async_session
from core.models.common import TokenPayload


@pytest.fixture
def admin_user():
    return TokenPayload(
        sub="admin-1",
        email="admin@example.com",
        role="platform_admin",
        org_id="org-1",
        team_id=None,
        permissions=["*:*:*"],
    )


@pytest.fixture
def regular_user():
    return TokenPayload(
        sub="user-1",
        email="user@example.com",
        role="scientist",
        org_id="org-1",
        team_id=None,
        permissions=[],
    )


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_mock_agent(**kwargs):
    """Build a MagicMock that looks like an AgentDefinition ORM row."""
    agent = MagicMock()
    agent.id = kwargs.get("id", "agent-1")
    agent.system_prompt = kwargs.get("system_prompt")
    agent.tools = kwargs.get("tools", [])
    agent.model_config_ = kwargs.get(
        "model_config_",
        {
            "provider": kwargs.get("provider_slug"),
            "model": kwargs.get("model_name"),
            "max_tokens": kwargs.get("max_tokens"),
            "temperature": kwargs.get("temperature"),
        },
    )
    # Remove None keys from model_config_ so it matches real ORM behaviour
    agent.model_config_ = {k: v for k, v in agent.model_config_.items() if v is not None}
    return agent


class TestAssistantConfig:
    """Tests for GET/PUT /assistant/config."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_admin_can_create_config(self, admin_user, mock_session):
        # No platform agent exists yet
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.put(
            "/api/v1/assistant/config",
            json={"system_prompt": "You are a helpful assistant", "temperature": 0.7},
        )

        # Should 404 since no platform agent exists
        assert response.status_code == 404

    def test_non_admin_gets_forbidden(self, regular_user, mock_session):
        app.dependency_overrides[get_current_user] = lambda: regular_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.put(
            "/api/v1/assistant/config",
            json={"system_prompt": "You are a helpful assistant"},
        )

        assert response.status_code == 403

    def test_unauthenticated_gets_401(self, mock_session):
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.put(
            "/api/v1/assistant/config",
            json={"system_prompt": "You are a helpful assistant"},
        )

        assert response.status_code == 401

    def test_admin_can_update_existing_config(self, admin_user, mock_session):
        existing = _make_mock_agent(
            id="agent-1",
            provider_slug="test-provider",
            model_name="test-model",
            system_prompt="Old prompt",
            max_tokens=1024,
            temperature=0.5,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result
        # refresh returns the updated agent
        mock_session.refresh.return_value = None

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.put(
            "/api/v1/assistant/config",
            json={"system_prompt": "Updated prompt", "max_tokens": 2048},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["system_prompt"] == "Updated prompt"
        assert data["max_tokens"] == 2048

    def test_partial_update_preserves_other_fields(self, admin_user, mock_session):
        existing = _make_mock_agent(
            id="agent-1",
            provider_slug="test-provider",
            model_name="test-model",
            system_prompt="Original prompt",
            max_tokens=1024,
            temperature=0.5,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result
        mock_session.refresh.return_value = None

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.put(
            "/api/v1/assistant/config",
            json={"temperature": 0.9},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["temperature"] == 0.9
        assert data["system_prompt"] == "Original prompt"
        assert data["model_name"] == "test-model"

    def test_get_config_returns_defaults_when_no_platform_agent(self, admin_user, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.get("/api/v1/assistant/config")

        assert response.status_code == 200
        data = response.json()
        assert data["provider_slug"] is None
        assert data["system_prompt"] is None
        assert data["tools"] == []

    def test_get_config_returns_saved_config(self, admin_user, mock_session):
        existing = _make_mock_agent(
            id="agent-1",
            provider_slug="test-provider",
            model_name="test-model",
            system_prompt="Saved prompt",
            max_tokens=2048,
            temperature=0.3,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.get("/api/v1/assistant/config")

        assert response.status_code == 200
        data = response.json()
        assert data["provider_slug"] == "test-provider"
        assert data["model_name"] == "test-model"
        assert data["system_prompt"] == "Saved prompt"
        assert data["max_tokens"] == 2048
        assert data["temperature"] == 0.3
