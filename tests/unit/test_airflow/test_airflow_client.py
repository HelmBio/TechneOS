"""Tests for the Airflow REST API client and configuration."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core.airflow.client import AirflowClient, AirflowClientError
from core.airflow.config import AirflowSettings


class TestAirflowSettings:
    """Test Airflow configuration from environment variables."""

    def test_defaults(self):
        settings = AirflowSettings(airflow_base_url="")
        assert settings.configured is False
        assert settings.airflow_username == "airflow"
        assert settings.airflow_dag_id == "techneos_airflow_pipeline"

    def test_configured_when_url_set(self):
        settings = AirflowSettings(airflow_base_url="http://airflow:8080")
        assert settings.configured is True
        assert settings.api_url == "http://airflow:8080/api/v1"

    def test_api_url_strips_trailing_slash(self):
        settings = AirflowSettings(airflow_base_url="http://airflow:8080/")
        assert settings.api_url == "http://airflow:8080/api/v1"


class TestAirflowClientStateMaps:
    """Test state mapping helpers."""

    def test_map_dag_run_state_success(self):
        assert AirflowClient.map_dag_run_state("success") == "completed"

    def test_map_dag_run_state_failed(self):
        assert AirflowClient.map_dag_run_state("failed") == "failed"

    def test_map_dag_run_state_running(self):
        assert AirflowClient.map_dag_run_state("running") == "running"

    def test_map_dag_run_state_queued(self):
        assert AirflowClient.map_dag_run_state("queued") == "queued"

    def test_map_dag_run_state_unknown_defaults_running(self):
        assert AirflowClient.map_dag_run_state("some_unknown") == "running"

    def test_map_task_state_success(self):
        assert AirflowClient.map_task_state("success") == "completed"

    def test_map_task_state_failed(self):
        assert AirflowClient.map_task_state("failed") == "failed"

    def test_map_task_state_skipped(self):
        assert AirflowClient.map_task_state("skipped") == "skipped"

    def test_map_task_state_scheduled(self):
        assert AirflowClient.map_task_state("scheduled") == "pending"

    def test_map_task_state_unknown_defaults_pending(self):
        assert AirflowClient.map_task_state("unknown_state") == "pending"


class TestAirflowClientAPI:
    """Test Airflow client DAG trigger and status operations."""

    @pytest.fixture
    def settings(self):
        return AirflowSettings(
            airflow_base_url="http://airflow:8080",
            airflow_username="admin",
            airflow_password="admin",
        )

    @pytest.fixture
    def client(self, settings):
        return AirflowClient(settings)

    async def test_trigger_dag_success(self, client):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "dag_run_id": "manual__2025-01-01",
            "state": "queued",
        }

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_resp)

        result = await client.trigger_dag("test_dag", conf={"run_id": "r1"})

        assert result["dag_run_id"] == "manual__2025-01-01"
        client._client.post.assert_called_once_with(
            "/dags/test_dag/dagRuns",
            json={"conf": {"run_id": "r1"}},
        )

    async def test_trigger_dag_failure_raises(self, client):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = False
        mock_resp.status_code = 404
        mock_resp.text = "DAG not found"

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(AirflowClientError, match="Airflow API error"):
            await client.trigger_dag("missing_dag")

    async def test_get_dag_run_status(self, client):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.json.return_value = {"state": "success"}

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_resp)

        status = await client.get_dag_run_status("dag1", "run1")
        assert status == "completed"

    async def test_cancel_dag_run(self, client):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.json.return_value = {"state": "failed"}

        client._client = AsyncMock()
        client._client.patch = AsyncMock(return_value=mock_resp)

        result = await client.cancel_dag_run("dag1", "run1")
        assert result["state"] == "failed"
        client._client.patch.assert_called_once_with(
            "/dags/dag1/dagRuns/run1",
            json={"state": "failed"},
        )

    async def test_get_task_instances(self, client):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "task_instances": [
                {"task_id": "prep", "state": "success"},
                {"task_id": "dock", "state": "running"},
            ]
        }

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_resp)

        tasks = await client.get_task_instances("dag1", "run1")
        assert len(tasks) == 2
        assert tasks[0]["task_id"] == "prep"

    async def test_get_task_logs(self, client):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.text = "Starting docking job...\nDocking complete."

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_resp)

        logs = await client.get_task_logs("dag1", "run1", "dock")
        assert "Docking complete" in logs

    async def test_context_manager(self, settings):
        async with AirflowClient(settings) as af:
            assert af._client is not None
        assert af._client is None
