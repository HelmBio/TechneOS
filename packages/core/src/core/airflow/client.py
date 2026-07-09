"""Async client for the Apache Airflow REST API (v1).

Provides methods to trigger DAG runs, poll status, fetch task instances,
and cancel runs.  Used by the pipeline orchestrator to dispatch work to
Airflow and keep the platform database in sync.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from core.airflow.config import AirflowSettings, get_airflow_settings

logger = logging.getLogger(__name__)

# Airflow DAG-run state mapping → platform run status
_AIRFLOW_STATE_MAP: dict[str, str] = {
    "queued": "queued",
    "running": "running",
    "success": "completed",
    "failed": "failed",
}

# Airflow task-instance state → platform step status
_AIRFLOW_TASK_STATE_MAP: dict[str, str] = {
    "queued": "pending",
    "scheduled": "pending",
    "running": "running",
    "success": "completed",
    "failed": "failed",
    "upstream_failed": "failed",
    "skipped": "skipped",
    "up_for_retry": "running",
    "up_for_reschedule": "running",
}


class AirflowClientError(Exception):
    """Raised when an Airflow API call fails."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class AirflowClient:
    """Async wrapper around the Airflow REST API.

    Usage::

        async with AirflowClient() as af:
            run = await af.trigger_dag("my_dag", conf={"key": "value"})

    Or inject settings explicitly::

        settings = AirflowSettings(airflow_base_url="http://airflow:8080")
        client = AirflowClient(settings)
    """

    def __init__(self, settings: AirflowSettings | None = None) -> None:
        self._settings = settings or get_airflow_settings()
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle --

    async def __aenter__(self) -> AirflowClient:
        self._client = self._build_client()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._settings.api_url,
            auth=(self._settings.airflow_username, self._settings.airflow_password),
            timeout=self._settings.airflow_timeout_seconds,
            headers={"Content-Type": "application/json"},
        )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- DAG runs --

    async def trigger_dag(
        self,
        dag_id: str,
        conf: dict[str, Any] | None = None,
        logical_date: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a new DAG run.

        Parameters
        ----------
        dag_id:
            The Airflow DAG identifier.
        conf:
            JSON-serialisable configuration passed to the DAG run.
        logical_date:
            Optional ISO-8601 logical date for the run.

        Returns
        -------
        dict
            The Airflow DAG run object (includes ``dag_run_id``, ``state``, etc.).
        """
        payload: dict[str, Any] = {"conf": conf or {}}
        if logical_date:
            payload["logical_date"] = logical_date

        resp = await self.client.post(f"/dags/{dag_id}/dagRuns", json=payload)
        self._raise_for_status(resp, f"trigger DAG {dag_id}")
        data = resp.json()
        logger.info("Triggered DAG %s → run_id=%s", dag_id, data.get("dag_run_id"))
        return cast(dict[str, Any], data)

    async def get_dag_run(self, dag_id: str, dag_run_id: str) -> dict[str, Any]:
        """Get details of a specific DAG run."""
        resp = await self.client.get(f"/dags/{dag_id}/dagRuns/{dag_run_id}")
        self._raise_for_status(resp, f"get DAG run {dag_id}/{dag_run_id}")
        return cast(dict[str, Any], resp.json())

    async def get_dag_run_status(self, dag_id: str, dag_run_id: str) -> str:
        """Return the platform-normalised status for a DAG run.

        Maps Airflow states (``queued``, ``running``, ``success``,
        ``failed``) to platform equivalents.
        """
        data = await self.get_dag_run(dag_id, dag_run_id)
        af_state = data.get("state", "queued")
        return _AIRFLOW_STATE_MAP.get(af_state, "running")

    async def cancel_dag_run(self, dag_id: str, dag_run_id: str) -> dict[str, Any]:
        """Cancel (mark as failed) a DAG run.

        Airflow does not have a dedicated cancel endpoint; the convention
        is to PATCH the run state to ``failed``.
        """
        resp = await self.client.patch(
            f"/dags/{dag_id}/dagRuns/{dag_run_id}",
            json={"state": "failed"},
        )
        self._raise_for_status(resp, f"cancel DAG run {dag_id}/{dag_run_id}")
        logger.info("Cancelled DAG run %s/%s", dag_id, dag_run_id)
        return cast(dict[str, Any], resp.json())

    # -- Task instances --

    async def get_task_instances(self, dag_id: str, dag_run_id: str) -> list[dict[str, Any]]:
        """List task instances for a DAG run."""
        resp = await self.client.get(f"/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances")
        self._raise_for_status(resp, f"list tasks {dag_id}/{dag_run_id}")
        return cast(list[dict[str, Any]], resp.json().get("task_instances", []))

    async def get_task_instance(self, dag_id: str, dag_run_id: str, task_id: str) -> dict[str, Any]:
        """Get a single task instance."""
        resp = await self.client.get(f"/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}")
        self._raise_for_status(resp, f"get task {dag_id}/{dag_run_id}/{task_id}")
        return cast(dict[str, Any], resp.json())

    async def get_task_logs(
        self,
        dag_id: str,
        dag_run_id: str,
        task_id: str,
        try_number: int = 1,
        map_index: int = -1,
    ) -> str:
        """Fetch logs for a task attempt."""
        if try_number < 1:
            return "Task has not started yet — no logs available."
        url = f"/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}/logs/{try_number}"
        params = {}
        if map_index >= 0:
            params["map_index"] = map_index
        resp = await self.client.get(
            url,
            params=params,
            headers={"Accept": "text/plain"},
        )
        self._raise_for_status(resp, f"get task logs {task_id}")
        return resp.text

    # -- helpers --

    @staticmethod
    def map_dag_run_state(airflow_state: str) -> str:
        """Map an Airflow DAG-run state to a platform run status."""
        return _AIRFLOW_STATE_MAP.get(airflow_state, "running")

    @staticmethod
    def map_task_state(airflow_state: str) -> str:
        """Map an Airflow task-instance state to a platform step status."""
        return _AIRFLOW_TASK_STATE_MAP.get(airflow_state, "pending")

    @staticmethod
    def _raise_for_status(resp: httpx.Response, action: str) -> None:
        if resp.is_success:
            return
        detail = resp.text[:500] if resp.text else "no body"
        msg = f"Airflow API error ({action}): {resp.status_code} — {detail}"
        logger.error(msg)
        raise AirflowClientError(msg, status_code=resp.status_code)
