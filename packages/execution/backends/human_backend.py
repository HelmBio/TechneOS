"""Human compute backend — creates task runs in task-service.

When a pipeline step uses a human-type tool, this backend creates a
TaskRun record in task-service and polls for its completion. The
assignee performs work offline and reports fulfillment through the
platform web UI.

Unlike DockerBackend / AWSBatchBackend, there is no container to pull,
no command to run, and no output directory to scan. The "job" completes
when the human reports results.

API endpoints used (all via the gateway → task-service):
    POST   /api/v1/task-runs                       create TaskRun
    GET    /api/v1/task-runs/{id}                  fetch status
    POST   /api/v1/task-runs/{id}/escalate         escalate to project lead
    POST   /api/v1/task-runs/{id}/cancel           cancel
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from backends.base import ComputeBackend, JobResult, JobSpec, JobStatus

logger = logging.getLogger(__name__)

# Polling cadence — applied to the dynamic interval HumanBackend computes
# from the remaining time before due_at. Without the cap, a task with a
# week-long deadline would not be polled for ~3.5 days (the previous
# "halve remaining time" strategy).
_MIN_POLL_INTERVAL = 15  # seconds — never poll faster than this
_MAX_POLL_INTERVAL = 15 * 60  # seconds — never wait longer than 15 min between polls
_BASE_POLL_INTERVAL = 60  # seconds — default when no due_at is set


class HumanBackend(ComputeBackend):
    """Backend that creates task runs in task-service and polls for fulfilment."""

    def __init__(self) -> None:
        self.api_url = ""
        self.token = ""
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            h["X-Internal-Token"] = self.token
        return h

    async def submit_job(self, spec: JobSpec) -> str:
        """Create a task run via task-service and return its ID."""
        self.api_url = spec.extra.get("callback_url", "")
        self.token = spec.extra.get("callback_token", "")

        due_at: str | None = None
        due_in_hours = spec.extra.get("due_in_hours")
        if due_in_hours:
            from datetime import timedelta

            due_at = (datetime.now(UTC) + timedelta(hours=int(due_in_hours))).isoformat()

        payload: dict[str, Any] = {
            "org_id": spec.extra.get("org_id", ""),
            "tool_slug": spec.extra.get("tool_slug", ""),
            "tool_version_id": spec.extra.get("tool_version_id", ""),
            "pipeline_run_id": spec.extra.get("pipeline_run_id") or spec.run_id or None,
            "pipeline_step_run_id": spec.extra.get("pipeline_step_run_id") or None,
            "step_name": spec.step_name,
            "input_snapshot": spec.extra.get("input_snapshot", {}),
            "assigned_user_id": spec.extra.get("assigned_user_id"),
            "assigned_user_email": spec.extra.get("assigned_user_email"),
            "assigned_team_slug": spec.extra.get("assigned_team_slug"),
            "project_lead_email": spec.extra.get("default_project_lead_email"),
            "due_at": due_at,
            "priority": spec.extra.get("priority", "medium"),
            "created_by": spec.extra.get("created_by") or None,
        }

        url = f"{self.api_url}/api/v1/task-runs"
        resp = await self.client.post(url, json=payload, headers=await self._headers())
        resp.raise_for_status()
        data = resp.json()
        task_run_id = data["id"]
        logger.info(
            "Created task run %s for step '%s' (tool=%s): %s",
            task_run_id,
            spec.step_name,
            payload["tool_slug"],
            payload["title"],
        )
        return task_run_id

    async def get_job_status(self, job_id: str) -> JobResult:
        """Poll the task run and compute the next dynamic poll interval."""
        if not self.api_url:
            return JobResult(
                job_id=job_id,
                status=JobStatus.FAILED,
                error_message="HumanBackend not configured with api_url",
            )

        url = f"{self.api_url}/api/v1/task-runs/{job_id}"
        resp = await self.client.get(url, headers=await self._headers())
        if resp.status_code == 404:
            return JobResult(
                job_id=job_id,
                status=JobStatus.FAILED,
                error_message="Task run not found",
            )
        resp.raise_for_status()
        data = resp.json()

        # Map status + outcome to JobStatus.
        status = data.get("status", "pending")
        outcome = data.get("outcome")
        job_status = self._map_status(status, outcome)

        # Dynamic poll interval: halve remaining time, capped to MAX.
        due_at_str = data.get("due_at")
        poll_interval = _BASE_POLL_INTERVAL
        if due_at_str:
            try:
                due_at = datetime.fromisoformat(due_at_str)
                remaining = (due_at - datetime.now(UTC)).total_seconds()
                if remaining > _MIN_POLL_INTERVAL:
                    poll_interval = max(_MIN_POLL_INTERVAL, int(remaining / 2))
                else:
                    poll_interval = _MIN_POLL_INTERVAL
            except (ValueError, TypeError):
                pass
        # Cap so a week-long deadline doesn't translate to a multi-day sleep.
        poll_interval = min(poll_interval, _MAX_POLL_INTERVAL)

        # Escalate when overdue and still active. task-service is idempotent
        # — escalating a run already assigned to its project lead is a no-op.
        if due_at_str and status in ("pending", "accepted", "in_progress"):
            try:
                if datetime.fromisoformat(due_at_str) < datetime.now(UTC):
                    esc_url = f"{self.api_url}/api/v1/task-runs/{job_id}/escalate"
                    await self.client.post(esc_url, headers=await self._headers())
                    logger.info("Escalated overdue task run %s to project lead", job_id)
            except (ValueError, TypeError):
                pass
            except httpx.HTTPError as exc:
                logger.warning("Failed to escalate task run %s: %s", job_id, exc)

        output_data = data.get("output_data") or {}
        logs_lines = [
            f"status: {status}",
            f"outcome: {outcome or '-'}",
            f"due_at: {due_at_str or 'not set'}",
            f"poll_interval: {poll_interval}s",
        ]
        if output_data:
            logs_lines.append(f"output: {output_data}")

        return JobResult(
            job_id=job_id,
            status=job_status,
            logs="\n".join(logs_lines),
            outputs=output_data if job_status == JobStatus.COMPLETED else {},
            error_message=data.get("error_message") if job_status == JobStatus.FAILED else None,
            extra={"poll_interval_hint": poll_interval},
        )

    async def cancel_job(self, job_id: str) -> None:
        if not self.api_url:
            return
        url = f"{self.api_url}/api/v1/task-runs/{job_id}/cancel"
        try:
            resp = await self.client.post(url, headers=await self._headers())
            resp.raise_for_status()
            logger.info("Cancelled task run %s", job_id)
        except httpx.HTTPError as exc:
            logger.warning("Failed to cancel task run %s: %s", job_id, exc)

    async def get_logs(self, job_id: str, tail: int = 500) -> str:
        result = await self.get_job_status(job_id)
        return result.logs

    async def collect_outputs(
        self,
        job_id: str,
        work_dir_host: str | None = None,
    ) -> dict[str, bytes]:
        """Return the submitted output_data as a JSON file.

        File attachments live in MinIO (referenced in
        ``output_data["attachments"]`` or as task_run_artifacts rows in
        task-service) and are not bundled here.
        """
        result = await self.get_job_status(job_id)
        if result.status != JobStatus.COMPLETED:
            return {}
        import json

        return {"output.json": json.dumps(result.outputs).encode("utf-8")}

    @staticmethod
    def _map_status(status: str, outcome: str | None) -> JobStatus:
        """Map task-service (status, outcome) to compute-backend JobStatus."""
        if status == "terminal":
            if outcome == "completed":
                return JobStatus.COMPLETED
            if outcome == "cancelled":
                return JobStatus.CANCELLED
            # declined / expired / anything else → failed
            return JobStatus.FAILED
        if status in ("pending", "accepted", "in_progress"):
            return JobStatus.RUNNING
        return JobStatus.RUNNING
