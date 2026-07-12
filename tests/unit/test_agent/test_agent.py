"""Tests for the agent service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agent_service.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestAgentHealth:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agent"


class TestAgentCRUD:
    """Test agent definition CRUD operations via mocked session."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    async def test_create_agent(self, mock_session):
        from agent_service.crud.agents import create_agent
        from core.schemas.agent import AgentCreate

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = AgentCreate(
            name="Docking Agent",
            slug="docking-agent",
            description="Automates molecular docking workflows",
            agent_type="autonomous",
            framework="langchain",
            tools=["autodock-vina", "ligand-prep"],
        )
        a = await create_agent(mock_session, data, org_id="org-1", user_id="user-1")

        assert a.name == "Docking Agent"
        assert a.slug == "docking-agent"
        assert a.agent_type == "autonomous"
        assert a.framework == "langchain"
        assert a.tools == ["autodock-vina", "ligand-prep"]
        mock_session.add.assert_called_once()

    async def test_create_agent_duplicate_slug(self, mock_session):
        from agent_service.crud.agents import create_agent
        from core.exceptions import AlreadyExistsError
        from core.schemas.agent import AgentCreate

        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = AgentCreate(name="Dup", slug="dup-agent")
        with pytest.raises(AlreadyExistsError):
            await create_agent(mock_session, data, org_id="org-1", user_id="user-1")

    async def test_get_agent_not_found(self, mock_session):
        from agent_service.crud.agents import get_agent
        from core.exceptions import NotFoundError

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await get_agent(mock_session, "nonexistent")

    async def test_search_agents_empty(self, mock_session):
        from agent_service.crud.agents import search_agents

        # First call returns count (scalar_one -> 0)
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        # Second call returns empty list
        mock_list_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_list_result.scalars.return_value = mock_scalars

        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_list_result])

        agents, total = await search_agents(mock_session)
        assert agents == []
        assert total == 0


class TestAgenticTaskCRUD:
    """Test agent run CRUD operations."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        return session

    async def test_create_run(self, mock_session):
        from agent_service.crud.runs import create_agentic_task

        run = await create_agentic_task(
            mock_session,
            agent_id="agent-1",
            task="Dock ligand ZINC000001 against target 1ABC",
            context={"dataset_id": "ds-1"},
            org_id="org-1",
            user_id="user-1",
        )

        assert run.agent_id == "agent-1"
        assert run.status == "pending"
        assert run.task == "Dock ligand ZINC000001 against target 1ABC"
        assert run.context == {"dataset_id": "ds-1"}
        assert run.submitted_by == "user-1"

    async def test_cancel_run_completed_fails(self, mock_session):
        from agent_service.crud.runs import cancel_agentic_task
        from core.exceptions import ValidationError

        mock_run = MagicMock()
        mock_run.status = "completed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_run
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValidationError, match="Cannot cancel"):
            await cancel_agentic_task(mock_session, "run-1")

    async def test_cancel_run_pending_succeeds(self, mock_session):
        from agent_service.crud.runs import cancel_agentic_task

        mock_run = MagicMock()
        mock_run.status = "pending"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_run
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await cancel_agentic_task(mock_session, "run-1")
        assert result.status == "cancelled"
        assert result.finished_at is not None


class TestAgentSchemas:
    """Test agent Pydantic schema validation."""

    def test_agent_create_valid(self):
        from core.schemas.agent import AgentCreate

        a = AgentCreate(
            name="Test Agent",
            slug="test-agent",
            agent_type="conversational",
            framework="custom",
        )
        assert a.agent_type == "conversational"
        assert a.framework == "custom"
        assert a.is_public is False
        assert a.tools == []

    def test_agent_create_invalid_slug(self):
        from pydantic import ValidationError

        from core.schemas.agent import AgentCreate

        with pytest.raises(ValidationError):
            AgentCreate(name="Bad", slug="UPPER-CASE-NOT-ALLOWED")

    def test_agent_run_create(self):
        from core.schemas.agent import AgenticTaskCreate

        run = AgenticTaskCreate(
            agent_id="agent-1",
            task="Perform docking analysis",
            parameters={"exhaustiveness": 8},
        )
        assert run.agent_id == "agent-1"
        assert run.task == "Perform docking analysis"
        assert run.parameters == {"exhaustiveness": 8}
        assert run.context == {}

    def test_agent_run_update_status_validation(self):
        from pydantic import ValidationError

        from core.schemas.agent import AgenticTaskUpdate

        with pytest.raises(ValidationError):
            AgenticTaskUpdate(status="invalid_status")


class TestAgentExecutor:
    """Test the agent executor protocol and implementations."""

    async def test_echo_executor(self):
        from core.agent import AgentContext, EchoAgentExecutor

        executor = EchoAgentExecutor()
        ctx = AgentContext(task="Hello, world!", parameters={"temp": 0.7})
        result = await executor.run("agent-1", ctx)

        assert result.status == "completed"
        assert result.result == {"echo": "Hello, world!"}
        assert len(result.messages) == 1
        assert result.messages[0]["content"] == "Echo: Hello, world!"
        assert result.tokens_used == 0

    def test_protocol_check(self):
        from core.agent import AgentExecutor, EchoAgentExecutor

        executor = EchoAgentExecutor()
        assert isinstance(executor, AgentExecutor)


class TestAgentModels:
    """Test agent ORM model definitions."""

    def test_agent_definition_model(self):
        from core.models.agent import AgentDefinition

        columns = AgentDefinition.__table__.columns.keys()
        expected = [
            "id",
            "created_at",
            "updated_at",
            "name",
            "slug",
            "description",
            "agent_type",
            "framework",
            "system_prompt",
            "model_config",
            "tools",
            "parameters_schema",
            "default_parameters",
            "tags",
            "is_public",
            "org_id",
            "created_by",
        ]
        for col in expected:
            assert col in columns, f"Missing column '{col}' in AgentDefinition"

    def test_agent_run_model(self):
        from core.models.agent import AgenticTask

        columns = AgenticTask.__table__.columns.keys()
        expected = [
            "id",
            "created_at",
            "updated_at",
            "agent_id",
            "status",
            "task",
            "context",
            "result",
            "messages",
            "tool_calls",
            "error_message",
            "tokens_used",
            "started_at",
            "finished_at",
            "org_id",
            "submitted_by",
        ]
        for col in expected:
            assert col in columns, f"Missing column '{col}' in AgenticTask"
