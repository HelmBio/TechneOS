"""Tests for tool-run submission, orchestrator, input staging."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.auth.dependencies import get_current_user
from core.database.postgres import get_async_session
from core.models.common import TokenPayload
from tool_service.main import app


def _make_mock_run(**kwargs) -> MagicMock:
    """Mock that looks like a ToolRun for Pydantic validation."""
    run = MagicMock()
    run.id = kwargs.get("id", "run-1")
    run.tool_version_id = kwargs.get("tool_version_id", "version-1")
    run.status = kwargs.get("status", "pending")
    run.parameters = kwargs.get("parameters", {})
    run.outputs = kwargs.get("outputs", {})
    run.error_message = None
    run.started_at = None
    run.finished_at = None
    run.airflow_dag_id = None
    run.airflow_run_id = None
    run.log_storage_key = kwargs.get("log_storage_key")
    run.org_id = kwargs.get("org_id", "org-1")
    run.submitted_by = "user-1"
    run.restarted_from = None
    # Denormalized fields are populated by from_orm_with_names from the
    # relationships below — initialise the mock attrs to None so the
    # explicit dict-build inside model_validate doesn't trip on MagicMocks.
    run.tool_id = None
    run.tool_slug = None
    run.tool_name = None
    run.tool_version_num = None
    run.submitted_by_email = None
    run.org_name = None

    run.tool_version = MagicMock()
    run.tool_version.id = kwargs.get("tool_version_id", "version-1")
    run.tool_version.version = 1
    run.tool_version.tool_id = "tool-1"
    run.tool_version.tool = MagicMock()
    run.tool_version.tool.slug = "admet-predictor"
    run.tool_version.tool.name = "ADMET Predictor"
    run.submitter = MagicMock()
    run.submitter.email = "user@example.com"
    run.org = MagicMock()
    run.org.name = "Test Org"
    run.created_at = "2026-05-25T12:00:00Z"
    run.updated_at = "2026-05-25T12:00:00Z"
    return run


@pytest.fixture
def auth_user():
    return TokenPayload(
        sub="user-1",
        email="user@example.com",
        role="scientist",
        org_id="org-1",
        team_id=None,
        permissions=["tool:read:team", "tool-run:execute:own", "tool-run:read:own"],
    )


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


class TestSubmitToolRun:
    def teardown_method(self):
        app.dependency_overrides.clear()

    @patch("tool_service.routes.runs.get_tool")
    @patch("tool_service.routes.runs.get_latest_version")
    @patch("tool_service.routes.runs.create_run")
    @patch("tool_service.routes.runs.get_run")
    @patch("tool_service.routes.runs.dispatch_tool_run")
    def test_submit_basic(
        self,
        mock_dispatch,
        mock_get_run,
        mock_create_run,
        mock_get_latest,
        mock_get_tool,
        auth_user,
        mock_session,
    ):
        mock_tool = MagicMock()
        mock_tool.org_id = "org-1"
        mock_get_tool.return_value = mock_tool

        mock_version = MagicMock()
        mock_version.id = "version-1"
        mock_version.tool_id = "tool-1"
        mock_version.parameters_schema = {
            "properties": {
                "endpoints": {"default": ["lipinski"]},
            },
        }
        mock_get_latest.return_value = mock_version

        mock_run = _make_mock_run()
        mock_create_run.return_value = mock_run
        mock_dispatch.return_value = mock_run
        mock_get_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/tool-runs",
            json={
                "tool_id": "tool-1",
                "parameters": {"smiles": ["CCO"]},
                "inputs": [],
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["id"] == "run-1"
        assert body["status"] == "pending"
        mock_create_run.assert_called_once()
        mock_dispatch.assert_called_once()
        # Schema default merged with user input
        _, kwargs = mock_create_run.call_args
        assert kwargs["parameters"]["endpoints"] == ["lipinski"]
        assert kwargs["parameters"]["smiles"] == ["CCO"]

    @patch("tool_service.routes.runs.get_tool")
    @patch("tool_service.routes.runs.get_latest_version")
    @patch("tool_service.routes.runs.create_run")
    @patch("tool_service.routes.runs.get_run")
    @patch("tool_service.routes.runs.create_artifact")
    @patch("tool_service.routes.runs.dispatch_tool_run")
    def test_submit_binds_inputs_and_rewrites_param(
        self,
        mock_dispatch,
        mock_create_artifact,
        mock_get_run,
        mock_create_run,
        mock_get_latest,
        mock_get_tool,
        auth_user,
        mock_session,
    ):
        mock_tool = MagicMock()
        mock_tool.org_id = "org-1"
        mock_get_tool.return_value = mock_tool

        mock_version = MagicMock()
        mock_version.id = "version-1"
        mock_version.tool_id = "tool-1"
        mock_version.version = 2
        mock_version.parameters_schema = {}
        mock_version.tool = MagicMock(slug="admet-predictor")
        mock_get_latest.return_value = mock_version

        mock_run = _make_mock_run()
        mock_create_run.return_value = mock_run
        mock_get_run.return_value = mock_run
        mock_dispatch.return_value = mock_run

        mock_artifact = MagicMock()
        mock_artifact.id = "artifact-1"
        mock_create_artifact.return_value = mock_artifact

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        with patch("core.storage.get_object_store") as mock_get_store:
            mock_store = MagicMock()
            mock_get_store.return_value = mock_store
            client = TestClient(app)
            response = client.post(
                "/api/v1/tool-runs",
                json={
                    "tool_id": "tool-1",
                    "parameters": {},
                    "inputs": [
                        {
                            "id": "input-1",
                            "parameter_name": "dataset",
                            "file_name": "mols.csv",
                            "content_type": "text/csv",
                            "source": "upload",
                            "storage_key": "scratch-space/tool-runs/admet-predictor/v2/input-1/mols.csv",
                        },
                    ],
                },
            )

        assert response.status_code == 201, response.text
        # Relocates the input from scratch to the canonical per-run prefix.
        mock_store.copy.assert_called_once_with(
            "techneos-data",
            "scratch-space/tool-runs/admet-predictor/v2/input-1/mols.csv",
            "techneos-data",
            "tool-runs/admet-predictor/v2/run-1/input/mols.csv",
        )
        mock_store.delete.assert_called_once_with(
            "techneos-data", "scratch-space/tool-runs/admet-predictor/v2/input-1/mols.csv"
        )

    @patch("tool_service.routes.runs.get_tool")
    @patch("tool_service.routes.runs.get_latest_version")
    @patch("tool_service.routes.runs.create_run")
    @patch("tool_service.routes.runs.get_run")
    @patch("tool_service.routes.runs.dispatch_tool_run")
    def test_submit_canonicalizes_dataset_ref(
        self,
        mock_dispatch,
        mock_get_run,
        mock_create_run,
        mock_get_latest,
        mock_get_tool,
        auth_user,
        mock_session,
    ):
        """Dataset slug strings in parameters become typed pointers."""
        mock_tool = MagicMock()
        mock_tool.org_id = "org-1"
        mock_get_tool.return_value = mock_tool

        mock_version = MagicMock()
        mock_version.id = "version-1"
        mock_version.tool_id = "tool-1"
        mock_version.parameters_schema = {}
        mock_get_latest.return_value = mock_version

        mock_run = _make_mock_run(parameters={"smiles": "pubchem-peptides:v3"})
        mock_create_run.return_value = mock_run
        mock_dispatch.return_value = mock_run
        mock_get_run.return_value = mock_run

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/tool-runs",
            json={
                "tool_id": "tool-1",
                "parameters": {"smiles": "pubchem-peptides:v3"},
                "input_ids": [],
            },
        )

        assert response.status_code == 201, response.text
        assert mock_run.parameters["smiles"] == {
            "type": "dataset",
            "ref": "pubchem-peptides:v3",
        }

    def test_submit_missing_org_id(self, mock_session):
        no_org = TokenPayload(
            sub="user-x",
            email="x@example.com",
            role="scientist",
            org_id=None,
            team_id=None,
            permissions=["tool-run:execute:own"],
        )
        app.dependency_overrides[get_current_user] = lambda: no_org
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/tool-runs",
            json={"tool_id": "tool-1", "parameters": {}, "input_ids": []},
        )
        assert response.status_code == 403


class TestOrchestrator:
    """Verify the single-step conf the orchestrator builds."""

    @pytest.fixture(autouse=True)
    def _clear_settings_cache(self):
        # get_settings() is lru_cache'd; tests that monkeypatch env vars
        # need a fresh Settings instance or they see a stale cached value.
        from core.config import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_build_single_step_conf_container(self):
        from tool_service.orchestrator import _build_single_step_conf

        tool = MagicMock(slug="admet-predictor", tool_type="container")
        tool_version = MagicMock(
            version=2,
            tool=tool,
            resource_requirements={"cpu": "1"},
            input_schema={
                "type": "object",
                "input_kind": "smiles_list",
                "properties": {"smiles": {"type": "array"}},
            },
            container_config=MagicMock(docker_image="techneos/admet", docker_tag="v2"),
            pypi_config=None,
        )

        conf = _build_single_step_conf(tool_version, {"smiles": ["CCO"]}, run_id="run-xyz")

        assert conf["tool_slug"] == "admet-predictor"
        assert conf["tool_type"] == "container"
        assert conf["image"] == "techneos/admet"
        assert conf["image_tag"] == "v2"
        assert conf["parameters"] == {"smiles": ["CCO"], "smiles_list_key": "smiles"}
        assert conf["depends_on"] == []
        assert conf["name"] == "admet-predictor"
        # Plan B: input_schema property names threaded through for the worker.
        assert conf["input_keys"] == ["smiles"]
        # Tool-wide input contract pulled from the top of input_schema.
        assert conf["input_kind"] == "smiles_list"
        # Auto-detected smiles_list_key from the first array property.
        assert conf["parameters"]["smiles_list_key"] == "smiles"
        # Artifact storage prefix: tool-runs/{slug}/v{N}/{run_id}
        assert conf["key_prefix"] == "tool-runs/admet-predictor/v2/run-xyz/output"

    def test_build_single_step_conf_pypi(self):
        from tool_service.orchestrator import _build_single_step_conf

        tool = MagicMock(slug="csv-filter", tool_type="pypi")
        tool_version = MagicMock(
            version=1,
            tool=tool,
            resource_requirements={},
            container_config=None,
            pypi_config=MagicMock(
                package_name="csv-filter",
                package_version="0.2.0",
                entry_point="csv_filter.filter:run",
                package_index_url="http://devpi:8080/",
            ),
        )

        conf = _build_single_step_conf(tool_version, {})

        assert conf["tool_type"] == "pypi"
        assert conf["image"] == ""
        assert conf["package_name"] == "csv-filter"
        assert conf["entry_point"] == "csv_filter.filter:run"

    def test_pypi_index_url_falls_back_to_env_var(self, monkeypatch):
        """When the per-tool URL is NULL, the deployment env var fills in."""
        from tool_service.orchestrator import _build_single_step_conf

        monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", "http://devpi:8080/simple/")

        tool = MagicMock(slug="csv-filter", tool_type="pypi")
        tool_version = MagicMock(
            version=1,
            tool=tool,
            resource_requirements={},
            container_config=None,
            pypi_config=MagicMock(
                package_name="csv-filter",
                package_version="0.2.0",
                entry_point="csv_filter.filter:run",
                package_index_url=None,
            ),
        )

        conf = _build_single_step_conf(tool_version, {})
        assert conf["package_index_url"] == "http://devpi:8080/simple/"

    def test_pypi_index_url_rewrites_localhost_for_tool_container(self, monkeypatch):
        """`localhost` is rewritten to `host.docker.internal` so the
        tool container can reach pypiserver running on the host."""
        from tool_service.orchestrator import _build_single_step_conf

        monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", "http://localhost:3141/simple/")

        tool = MagicMock(slug="csv-filter", tool_type="pypi")
        tool_version = MagicMock(
            version=1,
            tool=tool,
            resource_requirements={},
            container_config=None,
            pypi_config=MagicMock(
                package_name="csv-filter",
                package_version="0.2.0",
                entry_point="csv_filter.filter:run",
                package_index_url=None,
            ),
        )

        conf = _build_single_step_conf(tool_version, {})
        assert conf["package_index_url"] == "http://host.docker.internal:3141/simple/"

    def test_pypi_index_url_rewrites_127_0_0_1(self, monkeypatch):
        from tool_service.orchestrator import _build_single_step_conf

        monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", "http://127.0.0.1:3141/simple/")

        tool = MagicMock(slug="csv-filter", tool_type="pypi")
        tool_version = MagicMock(
            version=1,
            tool=tool,
            resource_requirements={},
            container_config=None,
            pypi_config=MagicMock(
                package_name="csv-filter",
                package_version="0.2.0",
                entry_point="csv_filter.filter:run",
                package_index_url=None,
            ),
        )

        conf = _build_single_step_conf(tool_version, {})
        assert conf["package_index_url"] == "http://host.docker.internal:3141/simple/"

    def test_pypi_index_url_leaves_other_hosts_alone(self, monkeypatch):
        """Compose service names, CodeArtifact URLs, and host.docker.internal
        itself all pass through unchanged."""
        from core.config import get_settings
        from tool_service.orchestrator import _build_single_step_conf

        for url in (
            "http://devpi:8080/simple/",
            "http://host.docker.internal:3141/simple/",
            "https://aws:tok@dom-123.d.codeartifact.us-east-1.amazonaws.com/pypi/r/simple/",
        ):
            monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", url)
            get_settings.cache_clear()
            tool = MagicMock(slug="csv-filter", tool_type="pypi")
            tool_version = MagicMock(
                version=1,
                tool=tool,
                resource_requirements={},
                container_config=None,
                pypi_config=MagicMock(
                    package_name="csv-filter",
                    package_version="0.2.0",
                    entry_point="csv_filter.filter:run",
                    package_index_url=None,
                ),
            )
            conf = _build_single_step_conf(tool_version, {})
            assert conf["package_index_url"] == url, f"{url} got rewritten"

    def test_pypi_index_url_preserves_credentials_when_rewriting(self, monkeypatch):
        """A localhost URL with basic-auth credentials keeps them after rewrite."""
        from tool_service.orchestrator import _build_single_step_conf

        monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", "http://user:pass@localhost:3141/simple/")

        tool = MagicMock(slug="csv-filter", tool_type="pypi")
        tool_version = MagicMock(
            version=1,
            tool=tool,
            resource_requirements={},
            container_config=None,
            pypi_config=MagicMock(
                package_name="csv-filter",
                package_version="0.2.0",
                entry_point="csv_filter.filter:run",
                package_index_url=None,
            ),
        )

        conf = _build_single_step_conf(tool_version, {})
        assert conf["package_index_url"] == "http://user:pass@host.docker.internal:3141/simple/"

    def test_pypi_per_tool_url_overrides_env(self, monkeypatch):
        """A non-NULL per-tool URL wins over the env var (used for tools
        that genuinely ship from a different index)."""
        from tool_service.orchestrator import _build_single_step_conf

        monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", "http://localhost:3141/simple/")

        tool = MagicMock(slug="csv-filter", tool_type="pypi")
        tool_version = MagicMock(
            version=1,
            tool=tool,
            resource_requirements={},
            container_config=None,
            pypi_config=MagicMock(
                package_name="csv-filter",
                package_version="0.2.0",
                entry_point="csv_filter.filter:run",
                package_index_url="https://partner.example.com/simple/",
            ),
        )

        conf = _build_single_step_conf(tool_version, {})
        # Partner URL passes through (not localhost, so no rewrite either).
        assert conf["package_index_url"] == "https://partner.example.com/simple/"


class TestStatusCallbackTimestamps:
    """The /tool-runs/{run_id}/steps/{step}/status callback should stamp
    started_at / finished_at so the UI's DURATION column has data to
    compute from."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    @patch("tool_service.routes.runs.check_resource_access")
    @patch("tool_service.routes.runs.update_run")
    @patch("tool_service.routes.runs.get_run")
    def test_running_transition_sets_started_at(
        self, mock_get_run, mock_update_run, _mock_check, auth_user, mock_session
    ):
        run = _make_mock_run(status="queued")
        run.started_at = None
        run.finished_at = None
        run.outputs = {}
        mock_get_run.return_value = run

        updated = _make_mock_run(status="running")
        mock_update_run.return_value = updated

        callback_user = TokenPayload(
            sub="user-1",
            email="user@example.com",
            role="scientist",
            org_id="org-1",
            team_id=None,
            permissions=["tool-run:update:own"],
        )
        app.dependency_overrides[get_current_user] = lambda: callback_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.patch(
            "/api/v1/tool-runs/run-1/steps/molecule-property-calculator/status",
            json={"status": "running"},
        )
        assert response.status_code == 200, response.text
        # update_run was called with started_at set, finished_at left alone.
        _, kwargs = mock_update_run.call_args
        payload = kwargs.get("data") or mock_update_run.call_args[0][-1]
        assert payload.status == "running"
        assert payload.started_at is not None
        assert payload.finished_at is None

    @patch("tool_service.routes.runs.check_resource_access")
    @patch("tool_service.routes.runs.update_run")
    @patch("tool_service.routes.runs.get_run")
    def test_completed_transition_sets_finished_at(
        self, mock_get_run, mock_update_run, _mock_check, auth_user, mock_session
    ):
        from datetime import UTC, datetime

        run = _make_mock_run(status="running")
        run.started_at = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
        run.finished_at = None
        run.outputs = {}
        mock_get_run.return_value = run

        updated = _make_mock_run(status="completed")
        mock_update_run.return_value = updated

        callback_user = TokenPayload(
            sub="user-1",
            email="user@example.com",
            role="scientist",
            org_id="org-1",
            team_id=None,
            permissions=["tool-run:update:own"],
        )
        app.dependency_overrides[get_current_user] = lambda: callback_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.patch(
            "/api/v1/tool-runs/run-1/steps/molecule-property-calculator/status",
            json={"status": "completed"},
        )
        assert response.status_code == 200, response.text
        _, kwargs = mock_update_run.call_args
        payload = kwargs.get("data") or mock_update_run.call_args[0][-1]
        assert payload.status == "completed"
        # started_at NOT touched (already set on the run), finished_at IS set.
        assert payload.started_at is None
        assert payload.finished_at is not None

    @patch("tool_service.routes.runs.check_resource_access")
    @patch("tool_service.routes.runs.update_run")
    @patch("tool_service.routes.runs.get_run")
    def test_retry_does_not_overwrite_started_at(
        self, mock_get_run, mock_update_run, _mock_check, auth_user, mock_session
    ):
        """A failed → running re-callback keeps the original started_at."""
        from datetime import UTC, datetime

        original_started = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
        run = _make_mock_run(status="failed")
        run.started_at = original_started
        run.finished_at = datetime(2026, 5, 28, 12, 0, 30, tzinfo=UTC)
        run.outputs = {}
        mock_get_run.return_value = run

        updated = _make_mock_run(status="running")
        mock_update_run.return_value = updated

        callback_user = TokenPayload(
            sub="user-1",
            email="user@example.com",
            role="scientist",
            org_id="org-1",
            team_id=None,
            permissions=["tool-run:update:own"],
        )
        app.dependency_overrides[get_current_user] = lambda: callback_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.patch(
            "/api/v1/tool-runs/run-1/steps/molecule-property-calculator/status",
            json={"status": "retrying"},  # maps to running
        )
        assert response.status_code == 200, response.text
        _, kwargs = mock_update_run.call_args
        payload = kwargs.get("data") or mock_update_run.call_args[0][-1]
        # status maps retrying → running, but started_at stays unset in the
        # payload because the run already has one — we only stamp on the
        # first transition.
        assert payload.status == "running"
        assert payload.started_at is None


class TestInputStaging:
    """The /tool-runs/inputs endpoint stages files in MinIO scratch space (no DB row)."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    @patch("core.storage.get_object_store")
    def test_stage_input(self, mock_get_store, auth_user, mock_session):
        store = MagicMock()
        mock_get_store.return_value = store

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/tool-runs/inputs",
            files={"file": ("mols.csv", b"smiles\nCCO\n", "text/csv")},
            data={
                "parameter_name": "dataset",
                "tool_slug": "csv-filter",
                "tool_version": "1",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["parameter_name"] == "dataset"
        assert body["file_name"] == "mols.csv"
        assert body["source"] == "upload"
        store.put.assert_called_once()

    @patch("core.storage.get_object_store")
    def test_stage_paste_writes_to_minio_with_source_paste(
        self, mock_get_store, auth_user, mock_session
    ):
        """The /tool-runs/inputs/paste endpoint writes to MinIO scratch space."""
        store = MagicMock()
        mock_get_store.return_value = store

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.post(
            "/api/v1/tool-runs/inputs/paste",
            json={
                "parameter_name": "smiles",
                "content": "CCO\nc1ccccc1\n",
                "content_type": "text/plain",
                "tool_slug": "molecule-property-calculator",
                "tool_version": 1,
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["source"] == "paste"
        assert body["file_name"] == "paste.txt"
        store.put.assert_called_once()

    def test_stage_paste_rejects_oversize(self, auth_user, mock_session):
        """Pastes over the 5 MB cap are rejected so callers use upload instead."""
        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        oversized = "x" * (5 * 1024 * 1024 + 1)
        response = client.post(
            "/api/v1/tool-runs/inputs/paste",
            json={
                "parameter_name": "smiles",
                "content": oversized,
                "tool_slug": "molecule-property-calculator",
                "tool_version": 1,
            },
        )
        assert response.status_code == 413

    @patch("core.storage.get_object_store")
    def test_download_input_returns_presigned_url(
        self, mock_get_store, auth_user, mock_session
    ):
        """The download endpoint returns a presigned URL from the scratch key."""
        store = MagicMock()
        store.presigned_url.return_value = "https://minio.example/signed?token=abc"
        mock_get_store.return_value = store

        app.dependency_overrides[get_current_user] = lambda: auth_user
        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app)
        response = client.get(
            "/api/v1/tool-runs/inputs/input-1/download",
            params={
                "tool_slug": "csv-filter",
                "tool_version": 1,
                "file_name": "mols.csv",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["input_id"] == "input-1"
        assert body["download_url"] == "https://minio.example/signed?token=abc"
        assert body["expires_in_seconds"] == 3600
        store.presigned_url.assert_called_once_with(
            "techneos-data",
            "scratch-space/tool-runs/csv-filter/v1/input-1/mols.csv",
            expires_seconds=3600,
        )
