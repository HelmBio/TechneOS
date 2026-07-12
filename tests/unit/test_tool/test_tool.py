"""Tests for the tool registry service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from tool_service.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestToolHealth:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "tool-registry"


class TestToolCRUD:
    """Test tool CRUD operations via mocked session."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    async def test_create_tool(self, mock_session):
        from core.schemas.tool import ToolCreate
        from tool_service.crud.tools import create_tool

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = ToolCreate(
            name="AutoDock Vina",
            slug="autodock-vina",
            description="Molecular docking",
            category="docking",
        )
        t = await create_tool(mock_session, data, org_id="org-1", user_id="user-1")

        assert t.name == "AutoDock Vina"
        assert t.slug == "autodock-vina"
        assert t.category == "docking"
        mock_session.add.assert_called_once()

    async def test_create_tool_duplicate(self, mock_session):
        from core.exceptions import AlreadyExistsError
        from core.schemas.tool import ToolCreate
        from tool_service.crud.tools import create_tool

        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = ToolCreate(name="Dup", slug="dup-tool")
        with pytest.raises(AlreadyExistsError):
            await create_tool(mock_session, data, org_id="org-1", user_id="user-1")

    async def test_get_tool_not_found(self, mock_session):
        from core.exceptions import NotFoundError
        from tool_service.crud.tools import get_tool

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await get_tool(mock_session, "nonexistent")


class TestToolVersionCRUD:
    """Test tool version CRUD operations."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        return session

    async def test_create_tool_version(self, mock_session):
        from core.schemas.tool import ToolVersionCreate
        from tool_service.crud.versions import create_tool_version

        # Mock next_version_number
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no existing versions
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = ToolVersionCreate(
            docker_image="registry.example.com/autodock",
            docker_tag="v1.0",
            input_schema={"type": "object"},
            resource_requirements={"cpu": "2", "memory": "4Gi"},
        )
        v = await create_tool_version(mock_session, "tool-1", data, user_id="user-1")

        assert v.docker_image == "registry.example.com/autodock"
        assert v.docker_tag == "v1.0"
        assert v.version == 1
        assert v.status == "draft"

    async def test_get_tool_version_not_found(self, mock_session):
        from core.exceptions import NotFoundError
        from tool_service.crud.versions import get_tool_version

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.unique.return_value = mock_result
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await get_tool_version(mock_session, "nonexistent")

    async def test_delete_tool_version(self, mock_session):
        from tool_service.crud.versions import delete_tool_version

        existing = MagicMock()
        existing.id = "v-1"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_result.unique.return_value = mock_result
        mock_session.execute = AsyncMock(return_value=mock_result)

        await delete_tool_version(mock_session, "v-1")

        mock_session.delete.assert_called_once_with(existing)
        mock_session.flush.assert_called_once()

    async def test_delete_tool_version_not_found(self, mock_session):
        from core.exceptions import NotFoundError
        from tool_service.crud.versions import delete_tool_version

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.unique.return_value = mock_result
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await delete_tool_version(mock_session, "nonexistent")

    async def test_replace_tool_version_content(self, mock_session):
        from core.models.tool import ContainerConfig, ToolVersion
        from core.schemas.tool import ToolVersionContentReplace
        from tool_service.crud.versions import replace_tool_version_content

        # An editable (draft, no runs) version can have its content replaced.
        existing_version = ToolVersion(
            id="v-1",
            tool_id="tool-1",
            version=1,
            status="draft",
            input_schema={},
            output_schema={},
            parameters_schema={},
            resource_requirements={},
            created_by="user-1",
        )
        existing_version.container_config = ContainerConfig(
            tool_version_id="v-1",
            docker_image="old-image",
            docker_tag="old-tag",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_version
        mock_result.unique.return_value = mock_result
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=None)
        # tool_version_has_runs => no runs.
        mock_session.scalar = AsyncMock(return_value=None)

        data = ToolVersionContentReplace(
            docker_image="new-image",
            docker_tag="v2.0",
            input_schema={"type": "object", "properties": {}},
        )
        v = await replace_tool_version_content(mock_session, "v-1", data, user_id="user-1")

        assert v.docker_image == "new-image"
        assert v.docker_tag == "v2.0"
        assert v.input_schema == {"type": "object", "properties": {}}
        assert v.status == "draft"
        assert v.updated_by == "user-1"

    async def test_replace_tool_version_content_rejected_when_locked(self, mock_session):
        from core.exceptions import ConflictError
        from core.models.tool import ToolVersion
        from core.schemas.tool import ToolVersionContentReplace
        from tool_service.crud.versions import replace_tool_version_content

        # An active version's definition is frozen for traceability.
        active_version = ToolVersion(
            id="v-1",
            tool_id="tool-1",
            version=1,
            status="active",
            input_schema={},
            output_schema={},
            parameters_schema={},
            resource_requirements={},
            created_by="user-1",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active_version
        mock_result.unique.return_value = mock_result
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.scalar = AsyncMock(return_value=None)

        with pytest.raises(ConflictError):
            await replace_tool_version_content(
                mock_session, "v-1", ToolVersionContentReplace(docker_image="x"), user_id="user-1"
            )


class TestToolSchemas:
    """Test tool Pydantic schema validation."""

    def test_tool_create_valid(self):
        from core.schemas.tool import ToolCreate

        t = ToolCreate(name="Test Tool", slug="test-tool", category="scoring")
        assert t.category == "scoring"
        assert t.is_public is False

    def test_tool_create_invalid_category(self):
        from pydantic import ValidationError

        from core.schemas.tool import ToolCreate

        with pytest.raises(ValidationError):
            ToolCreate(name="Test", slug="test", category="invalid")

    def test_tool_version_create_defaults(self):
        from core.schemas.tool import ToolVersionCreate

        v = ToolVersionCreate(docker_image="img:latest")
        assert v.docker_tag is None  # DB column defaults to "latest"; schema allows None
        assert v.input_schema == {}
        assert v.resource_requirements == {}

    def test_tool_version_update_status_validation(self):
        from pydantic import ValidationError

        from core.schemas.tool import ToolVersionUpdate

        with pytest.raises(ValidationError):
            ToolVersionUpdate(status="invalid_status")

    def test_tool_version_create_accepts_known_input_kind(self):
        from core.schemas.tool import ToolVersionCreate

        v = ToolVersionCreate(
            docker_image="img:latest",
            input_schema={
                "type": "object",
                "input_kind": "smiles_list",
                "properties": {"smiles": {"type": "array"}},
            },
        )
        assert v.input_schema["input_kind"] == "smiles_list"

    def test_tool_version_create_accepts_omitted_input_kind(self):
        """Legacy tools that haven't declared a kind still register fine."""
        from core.schemas.tool import ToolVersionCreate

        v = ToolVersionCreate(
            docker_image="img:latest",
            input_schema={"type": "object", "properties": {}},
        )
        assert "input_kind" not in v.input_schema

    def test_tool_version_create_rejects_unknown_input_kind(self):
        from pydantic import ValidationError

        from core.schemas.tool import ToolVersionCreate

        with pytest.raises(ValidationError, match="helm_list"):
            ToolVersionCreate(
                docker_image="img:latest",
                input_schema={
                    "type": "object",
                    "input_kind": "helm_list",
                    "properties": {},
                },
            )

    def test_tool_version_create_rejects_wrong_case_input_kind(self):
        """Case-sensitive — 'SMILES_LIST' is not the same as 'smiles_list'."""
        from pydantic import ValidationError

        from core.schemas.tool import ToolVersionCreate

        with pytest.raises(ValidationError, match="SMILES_LIST"):
            ToolVersionCreate(
                docker_image="img:latest",
                input_schema={
                    "type": "object",
                    "input_kind": "SMILES_LIST",
                    "properties": {},
                },
            )

    def test_tool_version_update_rejects_unknown_input_kind(self):
        from pydantic import ValidationError

        from core.schemas.tool import ToolVersionUpdate

        with pytest.raises(ValidationError, match="bogus_kind"):
            ToolVersionUpdate(input_schema={"input_kind": "bogus_kind"})

    def test_tool_version_content_replace_rejects_unknown_input_kind(self):
        from pydantic import ValidationError

        from core.schemas.tool import ToolVersionContentReplace

        with pytest.raises(ValidationError, match="bogus_kind"):
            ToolVersionContentReplace(
                docker_image="img:latest",
                input_schema={"input_kind": "bogus_kind"},
            )

    def test_tool_version_content_replace_schema(self):
        """Container-type replace payload — the schema only accepts
        docker/pypi shapes (module tool_type is not supported)."""
        from core.schemas.tool import ToolVersionContentReplace

        data = ToolVersionContentReplace(
            docker_image="img:latest",
            docker_tag="2.0.0",
            resource_requirements={"cpu": "4"},
        )
        assert data.docker_image == "img:latest"
        assert data.docker_tag == "2.0.0"
        assert data.resource_requirements == {"cpu": "4"}

    def test_tool_version_content_replace_pypi_shape(self):
        """Pypi-type replace payload carries package coords."""
        from core.schemas.tool import ToolVersionContentReplace

        data = ToolVersionContentReplace(
            package_name="csv-filter",
            package_version="0.2.0",
            entry_point="csv_filter.filter:run",
            package_index_url="http://devpi:3141/",
            resource_requirements={"cpu": "0.25", "memory": "256Mi"},
        )
        assert data.package_name == "csv-filter"
        assert data.entry_point == "csv_filter.filter:run"


# The module-type runtime validation (TestRuntimeValidation) was deleted
# alongside the script_environment / tool_script columns. Pypi runtime
# validation is exercised by catalog/tools/csv-filter/tests/test_filter.py and the
# tool service's `/validate` endpoint integration tests.
