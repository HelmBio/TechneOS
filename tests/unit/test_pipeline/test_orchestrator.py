"""Tests for the pipeline orchestrator — dispatch, sync, cancel."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.airflow.config import AirflowSettings


class TestOrchestratorDispatch:
    """Test dispatch_run — sending a pipeline run to Airflow."""

    @pytest.fixture
    def settings_configured(self):
        return AirflowSettings(
            airflow_base_url="http://airflow:8080",
            airflow_dag_id="techneos_airflow_pipeline",
            platform_callback_url="http://gateway:8000",
        )

    @pytest.fixture
    def settings_unconfigured(self):
        return AirflowSettings(airflow_base_url="")

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def mock_definition(self):
        # The version is a binding over the parent's shape. The parent
        # pipeline holds shape-only steps; the version holds per-step bindings.
        defn = MagicMock()
        defn.version = 1
        defn.bindings = {
            "prep": {"tool_version": None, "parameters": {"pH": 7.4}},
            "dock": {"tool_version": None, "parameters": {"exhaustiveness": 32}},
        }
        pipeline = MagicMock()
        pipeline.slug = "dock-pipeline"
        pipeline.steps = [
            {
                "name": "prep",
                "tool_slug": "rdkit-prep",
                "resource_requirements": {"cpu": "2", "memory": "4Gi"},
                "depends_on": [],
            },
            {
                "name": "dock",
                "tool_slug": "autodock-vina",
                "resource_requirements": {"cpu": "4", "memory": "8Gi", "gpu": 1},
                "depends_on": ["prep"],
            },
        ]
        defn.pipeline = pipeline
        return defn

    @pytest.fixture
    def mock_run(self):
        run = MagicMock()
        run.id = "run-123"
        run.status = "pending"
        run.parameters = {"exhaustiveness": 32}
        run.airflow_dag_id = None
        run.airflow_run_id = None
        return run

    async def test_dispatch_skips_when_not_configured(
        self, mock_session, mock_run, mock_definition, settings_unconfigured
    ):
        from pipeline_service.orchestrator import dispatch_run

        result = await dispatch_run(
            mock_session, mock_run, mock_definition, settings=settings_unconfigured
        )
        # Run stays in pending — no Airflow call
        assert result.status == "pending"
        assert result.airflow_dag_id is None

    @patch("pipeline_service.orchestrator.AirflowClient")
    async def test_dispatch_triggers_airflow(
        self, MockClient, mock_session, mock_run, mock_definition, settings_configured
    ):
        from pipeline_service.orchestrator import dispatch_run

        # Mock the async context manager and trigger_dag
        mock_af = AsyncMock()
        mock_af.trigger_dag = AsyncMock(
            return_value={"dag_run_id": "manual__2025-01-15", "state": "queued"}
        )
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_af)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await dispatch_run(
            mock_session, mock_run, mock_definition, settings=settings_configured
        )

        assert result.status == "queued"
        assert result.airflow_dag_id == "techneos_airflow_pipeline"
        assert result.airflow_run_id == "manual__2025-01-15"
        mock_af.trigger_dag.assert_called_once()

        # Verify conf structure
        call_kwargs = mock_af.trigger_dag.call_args
        conf = call_kwargs[1]["conf"] if "conf" in call_kwargs[1] else call_kwargs[0][1]
        assert conf["run_id"] == "run-123"
        assert len(conf["steps"]) == 2

    @patch("pipeline_service.orchestrator.AirflowClient")
    async def test_dispatch_handles_airflow_error(
        self, MockClient, mock_session, mock_run, mock_definition, settings_configured
    ):
        from core.airflow.client import AirflowClientError
        from pipeline_service.orchestrator import dispatch_run

        mock_af = AsyncMock()
        mock_af.trigger_dag = AsyncMock(
            side_effect=AirflowClientError("Connection refused", status_code=None)
        )
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_af)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await dispatch_run(
            mock_session, mock_run, mock_definition, settings=settings_configured
        )

        assert result.status == "failed"
        assert "Airflow dispatch failed" in result.error_message


class TestOrchestratorSync:
    """Test sync_run_status — polling Airflow and updating DB."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def settings(self):
        return AirflowSettings(airflow_base_url="http://airflow:8080")

    async def test_sync_skips_when_no_airflow_refs(self, mock_session, settings):
        from pipeline_service.orchestrator import sync_run_status

        run = MagicMock()
        run.airflow_dag_id = None
        run.airflow_run_id = None
        run.status = "pending"

        result = await sync_run_status(mock_session, run, settings=settings)
        assert result.status == "pending"

    async def test_sync_skips_terminal_state(self, mock_session, settings):
        from pipeline_service.orchestrator import sync_run_status

        run = MagicMock()
        run.airflow_dag_id = "dag1"
        run.airflow_run_id = "run1"
        run.status = "completed"

        result = await sync_run_status(mock_session, run, settings=settings)
        assert result.status == "completed"


class TestOrchestratorCancel:
    """Test handle_cancel — cancelling in both platform and Airflow."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        # get_step_runs() does session.execute(...).scalars().all() — those are
        # sync calls on the awaited result, not further AsyncMock coroutines.
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)
        return session

    @patch("pipeline_service.orchestrator.AirflowClient")
    async def test_cancel_with_airflow(self, MockClient, mock_session):
        from pipeline_service.orchestrator import handle_cancel

        settings = AirflowSettings(airflow_base_url="http://airflow:8080")

        run = MagicMock()
        run.id = "run-1"
        run.airflow_dag_id = "dag1"
        run.airflow_run_id = "run1"
        run.status = "running"

        mock_af = AsyncMock()
        mock_af.cancel_dag_run = AsyncMock(return_value={"state": "failed"})
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_af)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await handle_cancel(mock_session, run, settings=settings)
        assert result.status == "cancelled"
        assert result.finished_at is not None
        mock_af.cancel_dag_run.assert_called_once()

    async def test_cancel_without_airflow(self, mock_session):
        from pipeline_service.orchestrator import handle_cancel

        settings = AirflowSettings(airflow_base_url="")

        run = MagicMock()
        run.id = "run-2"
        run.airflow_dag_id = None
        run.airflow_run_id = None
        run.status = "pending"

        result = await handle_cancel(mock_session, run, settings=settings)
        assert result.status == "cancelled"


class TestBuildStepConfs:
    """Test the internal _build_step_confs helper."""

    async def test_builds_correct_structure(self):
        from pipeline_service.orchestrator import _build_step_confs

        # Shape on the parent, bindings on the version.
        pipeline = MagicMock()
        pipeline.steps = [
            {
                "name": "prep",
                "tool_slug": "rdkit",
                "depends_on": [],
                "resource_requirements": {"cpu": "2"},
            },
        ]
        defn = MagicMock()
        defn.bindings = {"prep": {"tool_version": None, "parameters": {"pH": 7.4}}}

        run = MagicMock()
        run.parameters = {}

        confs = await _build_step_confs(defn, run, pipeline=pipeline)
        assert len(confs) == 1
        assert confs[0]["name"] == "prep"
        assert confs[0]["tool_slug"] == "rdkit"
        assert confs[0]["parameters"]["pH"] == 7.4
        assert confs[0]["depends_on"] == []

    async def test_includes_key_prefix_with_slug_and_version(self):
        """Artifact key prefix: pipeline-runs/{slug}/v{N}/{run_id}/{step_name}."""
        from pipeline_service.orchestrator import _build_step_confs

        pipeline = MagicMock()
        pipeline.steps = [
            {"name": "prep", "tool_slug": "rdkit", "depends_on": []},
            {"name": "dock", "tool_slug": "vina", "depends_on": ["prep"]},
        ]
        defn = MagicMock()
        defn.bindings = {
            "prep": {"tool_version": None, "parameters": {}},
            "dock": {"tool_version": None, "parameters": {}},
        }
        run = MagicMock()
        run.id = "run-123"
        run.parameters = {}

        confs = await _build_step_confs(
            defn,
            run,
            pipeline=pipeline,
            pipeline_slug="admet-discovery",
            pipeline_version_num=3,
        )

        assert confs[0]["key_prefix"] == "pipeline-runs/admet-discovery/v3/run-123/prep"
        assert confs[1]["key_prefix"] == "pipeline-runs/admet-discovery/v3/run-123/dock"

    async def test_key_prefix_empty_when_slug_missing(self):
        """Without slug/version the prefix is empty — worker falls back to legacy shape."""
        from pipeline_service.orchestrator import _build_step_confs

        pipeline = MagicMock()
        pipeline.steps = [{"name": "prep", "tool_slug": "rdkit", "depends_on": []}]
        defn = MagicMock()
        defn.bindings = {"prep": {"tool_version": None, "parameters": {}}}
        run = MagicMock()
        run.id = "run-456"
        run.parameters = {}

        confs = await _build_step_confs(defn, run, pipeline=pipeline)  # no slug args
        assert confs[0]["key_prefix"] == ""
