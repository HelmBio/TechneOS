"""Tests for pipeline run submission — POST /pipeline-runs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.auth.dependencies import get_current_user
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from pipeline_service.main import app


def _make_mock_run(**kwargs) -> MagicMock:
    """Create a MagicMock that looks like a PipelineRun for Pydantic validation."""
    run = MagicMock()
    run.id = kwargs.get("id", "run-1")
    run.version_id = kwargs.get("version_id", "version-1")
    run.name = kwargs.get("name")
    run.status = kwargs.get("status", "pending")
    run.parameters = kwargs.get("parameters", {})
    run.error_message = kwargs.get("error_message")
    run.started_at = kwargs.get("started_at")
    run.finished_at = kwargs.get("finished_at")
    run.airflow_dag_id = kwargs.get("airflow_dag_id")
    run.airflow_run_id = kwargs.get("airflow_run_id")
    run.org_id = kwargs.get("org_id", "org-1")
    run.submitted_by = kwargs.get("submitted_by", "user-1")
    run.restarted_from = kwargs.get("restarted_from")
    run.pipeline_id = kwargs.get("pipeline_id", "pipeline-1")
    run.pipeline_name = kwargs.get("pipeline_name", "Test Pipeline")
    run.pipeline_slug = kwargs.get("pipeline_slug", "test-pipeline")
    run.pipeline_version = kwargs.get("pipeline_version", 1)
    run.submitted_by_email = kwargs.get("submitted_by_email", "user@example.com")
    run.org_name = kwargs.get("org_name", "Test Org")
    run.version = MagicMock()
    run.version.version = kwargs.get("pipeline_version", 1)
    run.version.pipeline_id = kwargs.get("pipeline_id", "pipeline-1")
    run.version.pipeline = MagicMock()
    run.version.pipeline.name = kwargs.get("pipeline_name", "Test Pipeline")
    run.version.pipeline.slug = kwargs.get("pipeline_slug", "test-pipeline")
    run.submitter = MagicMock()
    run.submitter.email = kwargs.get("submitted_by_email", "user@example.com")
    run.org = MagicMock()
    run.org.name = kwargs.get("org_name", "Test Org")
    return run


@pytest.fixture
def auth_user():
    return TokenPayload(
        sub="user-1",
        email="user@example.com",
        role="scientist",
        org_id="org-1",
        team_id=None,
        permissions=["pipeline:execute:own", "pipeline-run:execute:own"],
    )


@pytest.fixture
def user_no_org():
    return TokenPayload(
        sub="user-2",
        email="user2@example.com",
        role="scientist",
        org_id=None,
        team_id=None,
        permissions=["pipeline:execute:own", "pipeline-run:execute:own"],
    )


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


class TestSubmitRun:
    """Tests for POST /pipeline-runs (submit_run endpoint)."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    @patch("pipeline_service.routes.runs.get_pipeline_by_slug")
    @patch("pipeline_service.routes.runs.get_latest_active_version")
    @patch("pipeline_service.routes.runs.create_run")
    @patch("pipeline_service.routes.runs.create_step_run")
    @patch("pipeline_service.routes.runs.dispatch_run")
    def test_submit_run_success(
        self,
        mock_dispatch_run,
        mock_create_step_run,
        mock_create_run,
        mock_get_latest_active_version,
        mock_get_pipeline_by_slug,
        auth_user,
        mock_session,
    ):
        # The parent holds the shape; the version holds bindings.
        mock_pipeline = MagicMock()
        mock_pipeline.id = "pipeline-1"
        mock_pipeline.org_id = "org-1"
        mock_pipeline.steps = [
            {"name": "prep", "tool_slug": "ligand-prep", "depends_on": []},
            {"name": "dock", "tool_slug": "autodock-vina", "depends_on": ["prep"]},
        ]
        mock_pipeline.parameters_schema = {"properties": {"exhaustiveness": {"default": 8}}}
        mock_get_pipeline_by_slug.return_value = mock_pipeline

        mock_version = MagicMock()
        mock_version.id = "version-1"
        mock_version.bindings = {
            "prep": {"tool_version": None, "parameters": {}},
            "dock": {"tool_version": None, "parameters": {"exhaustiveness": 8}},
        }
        mock_get_latest_active_version.return_value = mock_version

        mock_run = _make_mock_run()
        mock_create_run.return_value = mock_run
        mock_dispatch_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "pipeline-1",
                "parameters": {"exhaustiveness": 16},
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "pending"
        assert data["id"] == "run-1"
        assert data["version_id"] == "version-1"
        mock_get_pipeline_by_slug.assert_called_once_with(mock_session, "pipeline-1")
        mock_get_latest_active_version.assert_called_once_with(mock_session, "pipeline-1")
        mock_create_run.assert_called_once()
        mock_create_step_run.assert_called()
        mock_dispatch_run.assert_called_once()

    @patch("pipeline_service.routes.runs.get_pipeline_by_slug")
    @patch("pipeline_service.routes.runs.get_latest_active_version")
    @patch("pipeline_service.routes.runs.create_run")
    def test_submit_run_merges_parameters(
        self,
        mock_create_run,
        mock_get_latest_active_version,
        mock_get_pipeline_by_slug,
        auth_user,
        mock_session,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.id = "pipeline-1"
        mock_pipeline.org_id = "org-1"
        mock_get_pipeline_by_slug.return_value = mock_pipeline

        # Run-input defaults now live on the parent shape's parameters_schema.
        mock_pipeline.steps = [{"name": "dock", "tool_slug": "autodock-vina", "depends_on": []}]
        mock_pipeline.parameters_schema = {
            "properties": {"exhaustiveness": {"default": 8}, "mode": {"default": "rigid"}}
        }

        mock_version = MagicMock()
        mock_version.id = "version-1"
        mock_version.bindings = {"dock": {"tool_version": None, "parameters": {}}}
        mock_get_latest_active_version.return_value = mock_version

        mock_run = _make_mock_run(parameters={"exhaustiveness": 16, "mode": "rigid"})
        mock_create_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "pipeline-1",
                "parameters": {"exhaustiveness": 16},
            },
        )

        assert response.status_code == 201
        _, call_kwargs = mock_create_run.call_args
        assert call_kwargs["parameters"] == {"exhaustiveness": 16, "mode": "rigid"}

    def test_submit_run_missing_org_id(self, user_no_org, mock_session):
        app.dependency_overrides[get_current_user] = lambda: user_no_org
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "pipeline-1",
                "parameters": {},
            },
        )

        assert response.status_code == 403

    @patch("pipeline_service.routes.runs.get_pipeline_by_slug")
    def test_submit_run_unknown_slug_not_found(
        self,
        mock_get_pipeline_by_slug,
        auth_user,
        mock_session,
    ):
        # Slug lookup reports a miss by returning None rather than raising.
        mock_get_pipeline_by_slug.return_value = None

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "no-such-pipeline",
                "parameters": {},
            },
        )

        assert response.status_code == 404
        assert "no-such-pipeline" in response.json()["detail"]

    @patch("pipeline_service.routes.runs.get_pipeline")
    def test_submit_run_unknown_uuid_not_found(
        self,
        mock_get_pipeline,
        auth_user,
        mock_session,
    ):
        # A UUID-shaped id takes the by-id path, which raises instead.
        from core.exceptions import NotFoundError

        unknown = "0e5a1c9e-1f9d-4d9b-9c3a-6f0b2f7a1234"
        mock_get_pipeline.side_effect = NotFoundError("Pipeline", unknown)

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": unknown,
                "parameters": {},
            },
        )

        assert response.status_code == 404
        mock_get_pipeline.assert_called_once_with(mock_session, unknown)

    @patch("pipeline_service.routes.runs.get_pipeline_by_slug")
    @patch("pipeline_service.routes.runs.get_latest_active_version")
    def test_submit_run_no_active_version(
        self,
        mock_get_latest_active_version,
        mock_get_pipeline_by_slug,
        auth_user,
        mock_session,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.id = "pipeline-1"
        mock_pipeline.org_id = "org-1"
        mock_get_pipeline_by_slug.return_value = mock_pipeline
        mock_get_latest_active_version.return_value = None

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "pipeline-1",
                "parameters": {},
            },
        )

        assert response.status_code == 409
        assert "no active version" in response.json()["detail"].lower()

    @patch("pipeline_service.routes.runs.get_pipeline_by_slug")
    @patch("pipeline_service.crud.versions.get_pipeline_version")
    @patch("pipeline_service.routes.runs.create_run")
    def test_submit_run_specific_version(
        self,
        mock_create_run,
        mock_get_pipeline_version,
        mock_get_pipeline_by_slug,
        auth_user,
        mock_session,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.id = "pipeline-1"
        mock_pipeline.org_id = "org-1"
        mock_get_pipeline_by_slug.return_value = mock_pipeline

        mock_version = MagicMock()
        mock_version.id = "version-2"
        # The version must belong to the pipeline the slug resolved to.
        mock_version.pipeline_id = "pipeline-1"
        mock_version.default_parameters = {}
        mock_version.steps = [{"name": "dock", "tool_slug": "autodock-vina"}]
        mock_get_pipeline_version.return_value = mock_version

        mock_run = _make_mock_run(version_id="version-2")
        mock_create_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "pipeline-1",
                "version_id": "version-2",
                "parameters": {},
            },
        )

        assert response.status_code == 201
        mock_get_pipeline_version.assert_called_once_with(mock_session, "version-2")

    @patch("pipeline_service.routes.runs.get_pipeline_by_slug")
    @patch("pipeline_service.crud.versions.get_pipeline_version")
    def test_submit_run_version_mismatch(
        self,
        mock_get_pipeline_version,
        mock_get_pipeline_by_slug,
        auth_user,
        mock_session,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.id = "pipeline-1"
        mock_pipeline.org_id = "org-1"
        mock_get_pipeline_by_slug.return_value = mock_pipeline

        mock_version = MagicMock()
        mock_version.id = "version-2"
        mock_version.pipeline_id = "pipeline-OTHER"
        mock_version.default_parameters = {}
        mock_version.steps = []
        mock_get_pipeline_version.return_value = mock_version

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline-runs",
            json={
                "pipeline_id": "pipeline-1",
                "version_id": "version-2",
                "parameters": {},
            },
        )

        assert response.status_code == 400
        assert "does not belong" in response.json()["detail"]
