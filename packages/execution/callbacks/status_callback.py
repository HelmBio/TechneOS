"""Airflow callbacks that report DAG-level status to the platform API.

These are attached to the DAG's ``on_success_callback``,
``on_failure_callback``, and ``on_retry_callback`` so that when the
entire DAG run completes, fails, or retries, the platform's pipeline
run record is updated accordingly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def on_dag_success(context: Any) -> None:
    """Called when the DAG run succeeds — mark the platform run as completed."""
    _report_run_status(context, status="completed")


def on_dag_failure(context: Any) -> None:
    """Called when the DAG run fails — mark the platform run as failed."""
    error = ""
    exception = context.get("exception")
    if exception:
        error = str(exception)[:1000]
    _report_run_status(context, status="failed", error_message=error)


def on_dag_retry(context: Any) -> None:
    """Called when the task is about to be retried.

    Sets all non-completed steps to ``retrying`` so the UI reflects
    that a retry is pending rather than showing stale ``failed``/``skipped``.
    """
    dag_run = context.get("dag_run")
    if dag_run is None:
        return

    conf = dag_run.conf or {}
    run_id: str = conf.get("run_id", "")
    callback_url: str = conf.get("callback_url", "")
    callback_token: str = conf.get("callback_token", "")

    if not callback_url or not run_id:
        return

    # Fetch current step statuses
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{callback_url}/api/v1/pipeline-runs/{run_id}",
                headers={"X-Internal-Token": callback_token} if callback_token else {},
            )
            if not resp.is_success:
                logger.warning("on_dag_retry: failed to fetch run %s: %s", run_id, resp.status_code)
                return
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("on_dag_retry: error fetching run %s: %s", run_id, exc)
        return

    # Set non-completed steps to "retrying"
    headers = {"X-Internal-Token": callback_token} if callback_token else {}
    for step in data.get("steps", []):
        if step.get("status") != "completed":
            step_name = step.get("step_name", "")
            try:
                with httpx.Client(timeout=10) as client:
                    client.patch(
                        f"{callback_url}/api/v1/pipeline-runs/{run_id}/steps/{step_name}/status",
                        json={"status": "retrying"},
                        headers=headers,
                    )
                logger.info("on_dag_retry: set step '%s' to retrying for run %s", step_name, run_id)
            except httpx.HTTPError as exc:
                logger.warning("on_dag_retry: error setting step '%s': %s", step_name, exc)


def _report_run_status(
    context: Any,
    status: str,
    error_message: str | None = None,
) -> None:
    """PATCH the pipeline run status back to the platform API."""
    dag_run = context.get("dag_run")
    if dag_run is None:
        return

    conf = dag_run.conf or {}
    run_id: str = conf.get("run_id", "")
    callback_url: str = conf.get("callback_url", "")
    callback_token: str = conf.get("callback_token", "")

    if not callback_url or not run_id:
        logger.debug("No callback configured — skipping DAG status report")
        return

    url = f"{callback_url}/api/v1/pipeline-runs/{run_id}"
    now = datetime.now(UTC).isoformat()

    payload: dict[str, Any] = {
        "status": status,
        "finished_at": now,
    }
    if status == "running":
        payload = {"status": status, "started_at": now}
    if error_message:
        payload["error_message"] = error_message

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.patch(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {callback_token}"} if callback_token else {},
            )
            if resp.is_success:
                logger.info("Reported run %s status=%s", run_id, status)
            else:
                logger.warning(
                    "Callback failed for run %s: %s %s",
                    run_id,
                    resp.status_code,
                    resp.text[:200],
                )
    except httpx.HTTPError as exc:
        logger.warning("Callback error for run %s: %s", run_id, exc)
