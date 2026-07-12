"""Tests for pipeline run routes — list, get, update, cancel, restart, sync, logs, artifacts."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.auth.dependencies import get_current_user
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from pipeline_service.main import app


def _mock_run(**kw):
    r = MagicMock()
    # Set every field to real values so Pydantic model_validate succeeds
    for attr, default in [
        ("id", "run-1"),
        ("version_id", "version-1"),
        ("name", None),
        ("status", "pending"),
        ("parameters", {}),
        ("error_message", None),
        ("started_at", None),
        ("finished_at", None),
        ("airflow_dag_id", None),
        ("airflow_run_id", None),
        ("org_id", "org-1"),
        ("submitted_by", "user-1"),
        ("restarted_from", None),
        ("pipeline_id", "pipeline-1"),
        ("pipeline_name", "Test Pipeline"),
        ("pipeline_slug", None),
        ("pipeline_version", 1),
        ("submitted_by_email", "user@example.com"),
        ("org_name", "Test Org"),
        # Explicitly set to None so getattr returns None, not a MagicMock
        ("team_id", None),
        ("created_by", None),
        ("is_public", False),
    ]:
        setattr(r, attr, kw.get(attr, default))
    r.version = MagicMock()
    r.version.version = kw.get("pipeline_version", 1)
    r.version.pipeline_id = kw.get("pipeline_id", "pipeline-1")
    r.version.pipeline = MagicMock()
    r.version.pipeline.name = kw.get("pipeline_name", "Test Pipeline")
    r.version.pipeline.slug = kw.get("pipeline_slug", "test-pipeline")
    r.submitter = MagicMock()
    r.submitter.email = kw.get("submitted_by_email", "user@example.com")
    r.org = MagicMock()
    r.org.name = kw.get("org_name", "Test Org")
    return r


def _mock_step_run(**kw):
    s = MagicMock()
    for attr, default in [
        ("id", "sr-1"),
        ("run_id", "run-1"),
        ("step_name", "dock"),
        ("tool_version_id", None),
        ("status", "pending"),
        ("parameters", {}),
        ("outputs", {}),
        ("error_message", None),
        ("started_at", None),
        ("finished_at", None),
    ]:
        setattr(s, attr, kw.get(attr, default))
    return s


def _mock_artifact(**kw):
    a = MagicMock()
    kw.setdefault("io_type", "output")
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def _mock_session():
    s = AsyncMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    s.delete = AsyncMock()
    s.execute = AsyncMock()
    return s


@pytest.fixture
def auth_user():
    return TokenPayload(
        sub="user-1",
        email="u@example.com",
        role="scientist",
        org_id="org-1",
        team_id=None,
        permissions=[
            "pipeline:execute:own",
            "pipeline:read:own",
            "pipeline:update:own",
            "pipeline-run:execute:own",
            "pipeline-run:read:own",
            "pipeline-run:update:own",
        ],
    )


@pytest.fixture
def mock_session():
    return _mock_session()


def _setup_session_for_artifacts(session, artifacts=None):
    """Configure mock session.execute to return artifacts for inline PipelineRunArtifact query."""
    if artifacts is None:
        artifacts = []
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = artifacts
    session.execute.return_value = mock_result


class TestListRuns:
    @patch("pipeline_service.routes.runs.build_scope_filters")
    @patch("pipeline_service.routes.runs.list_runs")
    def test_list_runs_success(self, mock_list_runs, mock_build_scope, auth_user, mock_session):
        mock_build_scope.return_value = []
        mock_run = _mock_run(
            id="r-1",
            status="completed",
            org_id="org-1",
            version_id="v-1",
            parameters={},
            submitted_by="u-1",
            restarted_from=None,
            finished_at=None,
            started_at=None,
            error_message=None,
            airflow_dag_id=None,
            airflow_run_id=None,
        )
        mock_list_runs.return_value = ([mock_run], 1)

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline-runs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "r-1"
        mock_list_runs.assert_called_once()
        mock_build_scope.assert_called_once()

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestGetRun:
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_step_runs")
    @patch("pipeline_service.routes.runs.sync_run_status")
    def test_get_run_auto_sync_active(
        self,
        mock_sync,
        mock_get_step_runs,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1")
        mock_get_run.return_value = mock_run

        mock_step = _mock_step_run(status="running")
        mock_get_step_runs.return_value = [mock_step]

        mock_synced_run = _mock_run(id="r-1", status="running")
        mock_sync.return_value = mock_synced_run

        _setup_session_for_artifacts(mock_session, [])

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline-runs/r-1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "r-1"
        assert "steps" in data
        assert "artifacts" in data
        mock_sync.assert_called_once()

    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_step_runs")
    def test_get_run_terminal_skips_sync(
        self,
        mock_get_step_runs,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="completed", org_id="org-1")
        mock_get_run.return_value = mock_run
        mock_step = _mock_step_run(status="completed")
        mock_get_step_runs.return_value = [mock_step]
        _setup_session_for_artifacts(mock_session, [])

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline-runs/r-1")
        assert resp.status_code == 200

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestUpdateRun:
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_pipeline")
    @patch("pipeline_service.routes.runs.update_run")
    @patch("pipeline_service.routes.runs.publish_pipeline_run_completed")
    def test_update_run_to_completed_fires_event(
        self,
        mock_publish,
        mock_update_run,
        mock_get_pipeline,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1", submitted_by="user-1")
        mock_get_run.return_value = mock_run

        mock_updated = _mock_run(
            id="r-1", status="completed", org_id="org-1", submitted_by="user-1"
        )
        mock_update_run.return_value = mock_updated

        mock_pipeline = MagicMock()
        mock_pipeline.id = "p-1"
        mock_pipeline.name = "Test Pipeline"
        mock_get_pipeline.return_value = mock_pipeline

        _setup_session_for_artifacts(mock_session)

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.patch(
            "/api/v1/pipeline-runs/r-1",
            json={"status": "completed"},
        )
        assert resp.status_code == 200
        mock_publish.assert_called_once()

    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_pipeline")
    @patch("pipeline_service.routes.runs.update_run")
    @patch("pipeline_service.routes.runs.publish_pipeline_run_failed")
    def test_update_run_to_failed_fires_event(
        self,
        mock_publish,
        mock_update_run,
        mock_get_pipeline,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1", submitted_by="user-1")
        mock_get_run.return_value = mock_run

        mock_updated = _mock_run(id="r-1", status="failed", org_id="org-1", submitted_by="user-1")
        mock_update_run.return_value = mock_updated

        mock_pipeline = MagicMock()
        mock_pipeline.id = "p-1"
        mock_pipeline.name = "Test Pipeline"
        mock_get_pipeline.return_value = mock_pipeline

        _setup_session_for_artifacts(mock_session)

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.patch(
            "/api/v1/pipeline-runs/r-1",
            json={"status": "failed", "error_message": "OOM"},
        )
        assert resp.status_code == 200
        mock_publish.assert_called_once()

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestCancelRun:
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.handle_cancel")
    def test_cancel_run_success(self, mock_handle_cancel, mock_get_run, auth_user, mock_session):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1")
        mock_get_run.return_value = mock_run

        mock_cancelled = _mock_run(id="r-1", status="cancelled", org_id="org-1")
        mock_handle_cancel.return_value = mock_cancelled

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post("/api/v1/pipeline-runs/r-1/cancel")
        assert resp.status_code == 200
        mock_handle_cancel.assert_called_once_with(mock_session, mock_run)

    @patch("pipeline_service.routes.runs.get_run")
    def test_cancel_run_terminal_state_raises(self, mock_get_run, auth_user, mock_session):
        mock_run = _mock_run(id="r-1", status="completed", org_id="org-1")
        mock_get_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post("/api/v1/pipeline-runs/r-1/cancel")
        assert resp.status_code == 422

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestRestartRun:
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_pipeline")
    @patch("pipeline_service.routes.runs.create_run")
    @patch("pipeline_service.routes.runs.create_step_run")
    @patch("pipeline_service.routes.runs.dispatch_run")
    def test_restart_run_success(
        self,
        mock_dispatch,
        mock_create_step_run,
        mock_create_run,
        mock_get_pipeline,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        version = MagicMock()
        version.id = "v-1"
        version.steps = [{"name": "dock", "tool_slug": "autodock-vina"}]
        version.pipeline_id = "pipeline-1"
        version.default_parameters = {}

        original = _mock_run(
            id="r-1",
            status="failed",
            org_id="org-1",
            version_id="v-1",
            submitted_by="user-1",
            parameters={"exhaustiveness": 8},
            version=version,
            name="My Run",
        )
        mock_get_run.return_value = original

        mock_pipeline = MagicMock()
        mock_pipeline.id = "p-1"
        mock_get_pipeline.return_value = mock_pipeline

        new_run = _mock_run(
            id="r-2",
            status="pending",
            org_id="org-1",
            version_id="v-1",
            submitted_by="user-1",
            parameters={"exhaustiveness": 8},
        )
        mock_create_run.return_value = new_run
        mock_dispatch.return_value = new_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post("/api/v1/pipeline-runs/r-1/restart")
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "r-2"
        mock_create_run.assert_called_once()
        mock_dispatch.assert_called_once()

    @patch("pipeline_service.routes.runs.get_run")
    def test_restart_run_non_terminal_raises_409(self, mock_get_run, auth_user, mock_session):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1")
        mock_get_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post("/api/v1/pipeline-runs/r-1/restart")
        assert resp.status_code == 409
        assert "failed or cancelled" in resp.json()["detail"].lower()

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestSyncRun:
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.sync_run_status")
    @patch("pipeline_service.routes.runs.get_step_runs")
    def test_sync_run_returns_detail(
        self,
        mock_get_step_runs,
        mock_sync,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1")
        mock_get_run.return_value = mock_run
        mock_sync.return_value = mock_run

        mock_step = _mock_step_run(
            status="completed", parameters={}, outputs={}, error_message=None
        )
        mock_get_step_runs.return_value = [mock_step]

        _setup_session_for_artifacts(mock_session, [])

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post("/api/v1/pipeline-runs/r-1/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "r-1"
        assert "steps" in data
        assert "artifacts" in data
        mock_sync.assert_called_once_with(mock_session, mock_run)

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestUpdateStepStatus:
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.update_step_run_by_name")
    def test_update_step_status_success(
        self,
        mock_update_step,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1")
        mock_get_run.return_value = mock_run

        mock_step = _mock_step_run(
            id="sr-1", status="completed", parameters={}, outputs={"result": 42}, error_message=None
        )
        mock_update_step.return_value = mock_step

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.patch(
            "/api/v1/pipeline-runs/r-1/steps/dock/status",
            json={"status": "completed", "outputs": {"result": 42}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "sr-1"
        assert data["status"] == "completed"
        mock_update_step.assert_called_once()

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestGetStepLogs:
    @patch("core.airflow.config.get_airflow_settings")
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_step_runs")
    def test_returns_container_logs(
        self,
        mock_get_step_runs,
        mock_get_run,
        mock_get_af_settings,
        auth_user,
        mock_session,
    ):
        from core.airflow.config import AirflowSettings

        mock_get_af_settings.return_value = AirflowSettings(
            airflow_base_url="http://airflow:8080",
            airflow_dag_id="test",
            platform_callback_url="http://gateway:8000",
        )
        mock_run = _mock_run(
            id="r-1",
            status="completed",
            org_id="org-1",
            airflow_dag_id="my-dag",
            airflow_run_id="my-run",
        )
        mock_get_run.return_value = mock_run

        mock_step = _mock_step_run(
            step_name="dock",
            outputs={"logs_tail": "Docking complete\nScore: -8.5"},
            error_message=None,
        )
        mock_get_step_runs.return_value = [mock_step]

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline-runs/r-1/steps/dock/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "Docking complete" in data["logs"]

    @patch("pipeline_service.routes.runs.get_run")
    def test_no_airflow_ref_raises_404(self, mock_get_run, auth_user, mock_session):
        mock_run = _mock_run(
            id="r-1", status="pending", org_id="org-1", airflow_dag_id=None, airflow_run_id=None
        )
        mock_get_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline-runs/r-1/steps/dock/logs")
        assert resp.status_code == 404

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestCreateArtifact:
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.create_artifact")
    def test_create_artifact_success(
        self, mock_create_artifact, mock_get_run, auth_user, mock_session
    ):
        mock_run = _mock_run(id="r-1", status="running", org_id="org-1")
        mock_get_run.return_value = mock_run

        mock_artifact = _mock_artifact(
            id="art-1",
            run_id="r-1",
            step_name="dock",
            name="output.pdb",
            artifact_type="file",
            file_name="output.pdb",
            file_size=1024,
            content_type="chemical/x-pdb",
            checksum_sha256="abc123",
            storage_bucket="pipelines",
            storage_key="r-1/output.pdb",
        )
        mock_create_artifact.return_value = mock_artifact

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post(
            "/api/v1/pipeline-runs/r-1/artifacts",
            json={
                "step_name": "dock",
                "name": "output.pdb",
                "artifact_type": "file",
                "file_name": "output.pdb",
                "file_size": 1024,
                "content_type": "chemical/x-pdb",
                "checksum_sha256": "abc123",
                "storage_bucket": "pipelines",
                "storage_key": "r-1/output.pdb",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "art-1"
        assert data["step_name"] == "dock"

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestDownloadArtifact:
    @patch("core.storage.get_object_store")
    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_artifact")
    def test_download_artifact_success(
        self,
        mock_get_artifact,
        mock_get_run,
        mock_get_store,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="completed", org_id="org-1")
        mock_get_run.return_value = mock_run

        mock_artifact = _mock_artifact(
            id="art-1",
            run_id="r-1",
            storage_bucket="pipelines",
            storage_key="r-1/out.pdb",
        )
        mock_get_artifact.return_value = mock_artifact

        mock_store = MagicMock()
        mock_store.presigned_url.return_value = "https://minio.example.com/presigned-url"
        mock_get_store.return_value = mock_store

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline-runs/r-1/artifacts/art-1/download")
        assert resp.status_code == 200
        data = resp.json()
        assert data["download_url"] == "https://minio.example.com/presigned-url"
        assert data["artifact_id"] == "art-1"
        mock_store.presigned_url.assert_called_once_with(
            "pipelines", "r-1/out.pdb", expires_seconds=3600
        )

    @patch("pipeline_service.routes.runs.get_run")
    @patch("pipeline_service.routes.runs.get_artifact")
    def test_download_artifact_mismatch_returns_404(
        self,
        mock_get_artifact,
        mock_get_run,
        auth_user,
        mock_session,
    ):
        mock_run = _mock_run(id="r-1", status="completed", org_id="org-1")
        mock_get_run.return_value = mock_run

        mock_artifact = _mock_artifact(id="art-1", run_id="OTHER-RUN")
        mock_get_artifact.return_value = mock_artifact

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline-runs/r-1/artifacts/art-1/download")
        assert resp.status_code == 404

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestStageInput:
    @patch("core.storage.get_object_store")
    def test_stage_paste_uses_pipeline_scratch_key(self, mock_get_store, auth_user, mock_session):
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post(
            "/api/v1/pipeline-runs/inputs/paste",
            json={
                "parameter_name": "ligands",
                "content": "CCO\nc1ccccc1",
                "content_type": "chemical/x-daylight-smiles",
                "pipeline_slug": "hit-triage",
                "pipeline_version": 2,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "paste"
        assert data["parameter_name"] == "ligands"
        assert data["storage_key"].startswith("scratch-space/pipeline-runs/hit-triage/v2/")
        mock_store.put.assert_called_once()

    def teardown_method(self):
        app.dependency_overrides.clear()


class TestSubmitRunInputs:
    @patch("pipeline_service.routes.runs.dispatch_run")
    @patch("pipeline_service.routes.runs.create_artifact")
    @patch("core.storage.get_object_store")
    @patch("pipeline_service.routes.runs.flag_modified")
    @patch("pipeline_service.routes.runs.create_step_run")
    @patch("pipeline_service.routes.runs.create_run")
    @patch("pipeline_service.routes.runs.schema_defaults")
    @patch("pipeline_service.routes.runs.merge")
    @patch("pipeline_service.routes.runs.check_resource_access")
    @patch("pipeline_service.routes.runs.get_latest_active_version")
    @patch("pipeline_service.routes.runs.get_pipeline")
    def test_submit_relocates_input_and_records_io_type_input(
        self,
        mock_get_pipeline,
        mock_get_version,
        mock_check_access,
        mock_merge,
        mock_schema_defaults,
        mock_create_run,
        mock_create_step_run,
        mock_flag_modified,
        mock_get_store,
        mock_create_artifact,
        mock_dispatch_run,
        auth_user,
        mock_session,
    ):
        # Pipeline with one x-input ('ligands') bound to the 'dock' step.
        mock_pipeline = MagicMock()
        mock_pipeline.slug = "hit-triage"
        mock_pipeline.steps = [{"name": "dock"}]
        mock_pipeline.parameters_schema = {
            "properties": {"ligands": {"x-input": True, "x-step": "dock"}}
        }
        mock_get_pipeline.return_value = mock_pipeline

        mock_version = MagicMock()
        mock_version.id = "v-1"
        mock_version.version = 2
        mock_version.bindings = {}
        mock_get_version.return_value = mock_version

        mock_merge.return_value = [{"name": "dock"}]
        mock_schema_defaults.return_value = {}

        mock_run = _mock_run(id="run-1", parameters={})
        mock_create_run.return_value = mock_run
        mock_dispatch_run.return_value = mock_run

        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        resp = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "pipeline-1",
                "parameters": {},
                "inputs": [
                    {
                        "id": "inp-1",
                        "parameter_name": "ligands",
                        "file_name": "ligs.smi",
                        "file_size": 12,
                        "content_type": "chemical/x-daylight-smiles",
                        "storage_bucket": "techneos-data",
                        "storage_key": "scratch-space/pipeline-runs/hit-triage/v2/inp-1/ligs.smi",
                        "source": "upload",
                        "checksum_sha256": "abc",
                    }
                ],
            },
        )
        assert resp.status_code == 201

        # The scratch file is relocated to the run's canonical inputs/ prefix.
        new_key = "pipeline-runs/hit-triage/v2/run-1/inputs/ligs.smi"
        mock_store.copy.assert_called_once_with(
            "techneos-data",
            "scratch-space/pipeline-runs/hit-triage/v2/inp-1/ligs.smi",
            "techneos-data",
            new_key,
        )
        mock_store.delete.assert_called_once()

        # An input artifact is recorded with io_type='input' and the owning step.
        kw = mock_create_artifact.call_args.kwargs
        assert kw["io_type"] == "input"
        assert kw["step_name"] == "dock"
        assert kw["storage_key"] == new_key
        assert kw["metadata"] == {"parameter_name": "ligands", "source": "upload"}

        # A namespaced typed pointer is injected into the run parameters.
        ptr = mock_run.parameters["dock.ligands"]
        assert ptr["type"] == "upload"
        assert ptr["storage_key"] == new_key

    def teardown_method(self):
        app.dependency_overrides.clear()
