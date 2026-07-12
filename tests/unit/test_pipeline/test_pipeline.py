"""Tests for the pipeline service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from pipeline_service.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestPipelineHealth:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "pipeline"


class TestPipelineCRUD:
    """Test pipeline definition CRUD operations."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        return session

    async def test_create_pipeline(self, mock_session):
        from core.schemas.pipeline import PipelineCreate, PipelineStepConfig
        from pipeline_service.crud.pipelines import create_pipeline

        mock_none = MagicMock()
        mock_none.scalar_one_or_none.return_value = None

        mock_tool = MagicMock()
        mock_tool.scalar_one_or_none.return_value = MagicMock()

        mock_pipeline_def = MagicMock()
        mock_pipeline_def.name = "Docking Pipeline"
        mock_pipeline_def.version = 1
        mock_pipeline_def.steps = [
            {"name": "prep", "tool_slug": "ligand-prep", "depends_on": [], "parameters": {}},
            {
                "name": "dock",
                "tool_slug": "autodock-vina",
                "depends_on": ["prep"],
                "parameters": {},
            },
        ]
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.scalar_one_or_none.return_value = mock_pipeline_def

        # validate_pipeline_type resolves (slug, tool_type) rows; container tools
        # imply "compute", which matches the default pipeline_type.
        mock_types = MagicMock()
        mock_types.all.return_value = [
            ("ligand-prep", "container"),
            ("autodock-vina", "container"),
        ]

        mock_session.execute = AsyncMock(
            side_effect=[
                mock_none,  # get_pipeline_by_slug
                mock_tool,  # validate: Tool lookup (ligand-prep)
                mock_tool,  # validate: ToolVersion active check (ligand-prep)
                mock_tool,  # validate: Tool lookup (autodock-vina)
                mock_tool,  # validate: ToolVersion active check (autodock-vina)
                mock_types,  # validate_pipeline_type: (slug, tool_type) rows
                mock_pipeline_result,  # get_pipeline
            ]
        )

        data = PipelineCreate(
            name="Docking Pipeline",
            slug="docking-pipeline",
            steps=[
                PipelineStepConfig(name="prep", tool_slug="ligand-prep"),
                PipelineStepConfig(name="dock", tool_slug="autodock-vina", depends_on=["prep"]),
            ],
            default_parameters={"exhaustiveness": 8},
        )
        p = await create_pipeline(mock_session, data, org_id="org-1", user_id="user-1")

        assert p.name == "Docking Pipeline"
        assert p.version == 1
        assert len(p.steps) == 2
        assert p.steps[0]["name"] == "prep"
        assert p.steps[1]["depends_on"] == ["prep"]

    async def test_create_pipeline_duplicate(self, mock_session):
        from core.exceptions import AlreadyExistsError
        from core.schemas.pipeline import PipelineCreate, PipelineStepConfig
        from pipeline_service.crud.pipelines import create_pipeline

        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = PipelineCreate(
            name="Dup",
            slug="dup-pipeline",
            steps=[PipelineStepConfig(name="s1", tool_slug="tool")],
        )
        with pytest.raises(AlreadyExistsError):
            await create_pipeline(mock_session, data, org_id="org-1", user_id="user-1")


class TestPipelineRunCRUD:
    """Test pipeline run CRUD operations."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()
        return session

    async def test_create_run(self, mock_session):
        from pipeline_service.crud.runs import create_run

        run = await create_run(
            mock_session,
            version_id="pipeline-1",
            parameters={"exhaustiveness": 16},
            org_id="org-1",
            user_id="user-1",
        )

        assert run.version_id == "pipeline-1"
        assert run.status == "pending"
        assert run.parameters == {"exhaustiveness": 16}
        assert run.submitted_by == "user-1"

    async def test_cancel_run_completed_fails(self, mock_session):
        from core.exceptions import ValidationError
        from pipeline_service.crud.runs import cancel_run

        mock_run = MagicMock()
        mock_run.status = "completed"
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalar_one_or_none.return_value = mock_run
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValidationError, match="Cannot cancel"):
            await cancel_run(mock_session, "run-1")

    async def test_cancel_run_pending_succeeds(self, mock_session):
        from pipeline_service.crud.runs import cancel_run

        mock_run = MagicMock()
        mock_run.status = "pending"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_run
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await cancel_run(mock_session, "run-1")
        assert result.status == "cancelled"
        assert result.finished_at is not None

    async def test_create_step_run(self, mock_session):
        from pipeline_service.crud.runs import create_step_run

        sr = await create_step_run(
            mock_session,
            run_id="run-1",
            step_name="dock",
            tool_version_id="tv-1",
            parameters={"mode": "rigid"},
        )
        assert sr.step_name == "dock"
        assert sr.status == "pending"
        assert sr.parameters == {"mode": "rigid"}


class TestPipelineSchemas:
    """Test pipeline Pydantic schema validation."""

    def test_pipeline_create_requires_steps(self):
        from pydantic import ValidationError

        from core.schemas.pipeline import PipelineCreate

        with pytest.raises(ValidationError):
            PipelineCreate(name="Empty", slug="empty", steps=[])

    def test_pipeline_step_config(self):
        from core.schemas.pipeline import PipelineStepConfig

        step = PipelineStepConfig(
            name="dock",
            tool_slug="autodock",
            tool_version=2,
            depends_on=["prep"],
        )
        assert step.tool_version == 2
        assert step.depends_on == ["prep"]

    def test_pipeline_run_create(self):
        from core.schemas.pipeline import PipelineRunCreate

        run = PipelineRunCreate(pipeline_id="pipe-1", parameters={"k": "v"})
        assert run.pipeline_id == "pipe-1"

    def test_pipeline_run_update_status_validation(self):
        from pydantic import ValidationError

        from core.schemas.pipeline import PipelineRunUpdate

        with pytest.raises(ValidationError):
            PipelineRunUpdate(status="invalid_status")

    def test_pipeline_run_detail_includes_steps_and_artifacts(self):
        from core.schemas.pipeline import PipelineRunDetail

        # Verify the model has steps and artifacts fields
        fields = PipelineRunDetail.model_fields
        assert "steps" in fields
        assert "artifacts" in fields


class TestPinToolVersion:
    """validate_tool_versions resolves tool_version=None to the
    currently-active version and writes the number back into the step.

    The DB lookups are mocked — these tests only assert the mutation
    behaviour and the error paths."""

    def _scalar_mock(self, value):
        """Helper: build a Result whose scalar_one_or_none() returns `value`."""
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=value)
        return result

    async def _run(self, session, steps):
        from pipeline_service.crud.versions import validate_tool_versions

        await validate_tool_versions(session, steps)

    async def test_unpinned_step_gets_pinned_to_latest_active(self, mock_session):
        from core.models.tool import Tool, ToolVersion

        tool = Tool(id="t-1", slug="admet-predictor", name="ADMET")
        latest = ToolVersion(tool_id="t-1", version=4, status="active")
        # First call: fetch tool. Second call: fetch latest active version.
        mock_session.execute = AsyncMock(
            side_effect=[
                self._scalar_mock(tool),
                self._scalar_mock(latest),
            ]
        )

        steps = [{"tool_slug": "admet-predictor", "tool_version": None}]
        await self._run(mock_session, steps)
        assert steps[0]["tool_version"] == 4

    async def test_explicit_version_left_alone(self, mock_session):
        from core.models.tool import Tool, ToolVersion

        tool = Tool(id="t-1", slug="admet-predictor", name="ADMET")
        v = ToolVersion(tool_id="t-1", version=2, status="active")
        mock_session.execute = AsyncMock(
            side_effect=[
                self._scalar_mock(tool),
                self._scalar_mock(v),
            ]
        )

        steps = [{"tool_slug": "admet-predictor", "tool_version": 2}]
        await self._run(mock_session, steps)
        assert steps[0]["tool_version"] == 2

    async def test_track_latest_keeps_tool_version_unset(self, mock_session):
        """Opt-out: track_latest=True means the orchestrator resolves at dispatch."""
        from core.models.tool import Tool, ToolVersion

        tool = Tool(id="t-1", slug="admet-predictor", name="ADMET")
        latest = ToolVersion(tool_id="t-1", version=5, status="active")
        mock_session.execute = AsyncMock(
            side_effect=[
                self._scalar_mock(tool),
                self._scalar_mock(latest),
            ]
        )

        steps = [
            {
                "tool_slug": "admet-predictor",
                "tool_version": None,
                "track_latest": True,
            }
        ]
        await self._run(mock_session, steps)
        # No pinning — still null so the dispatch-time resolver kicks in.
        assert steps[0]["tool_version"] is None

    async def test_pin_fails_when_no_active_version(self, mock_session):
        from fastapi import HTTPException

        from core.models.tool import Tool

        tool = Tool(id="t-1", slug="orphan", name="No Active")
        mock_session.execute = AsyncMock(
            side_effect=[
                self._scalar_mock(tool),
                self._scalar_mock(None),  # no active version
            ]
        )

        steps = [{"tool_slug": "orphan", "tool_version": None}]
        with pytest.raises(HTTPException) as exc:
            await self._run(mock_session, steps)
        assert exc.value.status_code == 400
        assert "no active version" in exc.value.detail.lower()

    async def test_explicit_inactive_version_rejected(self, mock_session):
        from fastapi import HTTPException

        from core.models.tool import Tool, ToolVersion

        tool = Tool(id="t-1", slug="admet-predictor", name="ADMET")
        deprecated_v = ToolVersion(tool_id="t-1", version=1, status="deprecated")
        mock_session.execute = AsyncMock(
            side_effect=[
                self._scalar_mock(tool),
                self._scalar_mock(deprecated_v),
            ]
        )

        with pytest.raises(HTTPException) as exc:
            await self._run(
                mock_session,
                [{"tool_slug": "admet-predictor", "tool_version": 1}],
            )
        assert exc.value.status_code == 400
        assert "deprecated" in exc.value.detail.lower() or "active" in exc.value.detail.lower()

    async def test_unknown_tool_rejected(self, mock_session):
        from fastapi import HTTPException

        mock_session.execute = AsyncMock(return_value=self._scalar_mock(None))
        with pytest.raises(HTTPException) as exc:
            await self._run(mock_session, [{"tool_slug": "does-not-exist"}])
        assert exc.value.status_code == 400
        assert "not found" in exc.value.detail.lower()
