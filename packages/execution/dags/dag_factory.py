"""Dynamic DAG factory for TechneOS pipelines.

This module registers a single Airflow DAG (id from the ``AIRFLOW_DAG_ID``
env var, default ``techneos_airflow_pipeline`` — must match ``core.airflow.config
.AirflowSettings.airflow_dag_id`` on the platform-service side)
that is parameterised entirely through the ``conf`` dict passed when
triggering a DAG run.  The conf is built by the platform's pipeline
orchestrator and contains all the information needed to reconstruct
the step graph and dispatch each step to a compute backend.

Expected ``conf`` structure::

    {
        "run_id": "<platform pipeline-run UUID>",
        "callback_url": "http://gateway:8000/api/v1/pipeline-runs/<run_id>",
        "callback_token": "<service-account JWT>",
        "steps": [
            {
                "name": "prep_ligands",
                "tool_slug": "rdkit-prep",
                "tool_version": 1,
                "image": "registry.example.com/rdkit-prep",
                "image_tag": "1.2.0",
                "parameters": {"pH": 7.4},
                "resource_requirements": {
                    "cpu": "2",
                    "memory": "4Gi",
                    "gpu": 0,
                    "backend": "docker"
                },
                "depends_on": []
            },
            {
                "name": "dock_vina",
                "tool_slug": "autodock-vina",
                ...
                "depends_on": ["prep_ligands"]
            }
        ]
    }

Steps are executed respecting ``depends_on`` edges: steps in the same
topological tier run in parallel; tiers execute sequentially.  If any
step fails, all downstream steps are skipped and the run is marked
failed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any

import httpx
from airflow import DAG
from airflow.models import DagRun
from airflow.utils.dates import days_ago
from callbacks.status_callback import on_dag_failure, on_dag_success
from operators.tool_operator import ToolOperator

logger = logging.getLogger(__name__)

# ── Default DAG arguments ────────────────────────────────────────────
default_args = {
    "owner": "techneos",
    "retries": int(os.getenv("AIRFLOW_TASK_RETRIES", "1")),
    "retry_delay": timedelta(minutes=int(os.getenv("AIRFLOW_RETRY_DELAY_MINUTES", "2"))),
    "execution_timeout": timedelta(hours=int(os.getenv("AIRFLOW_EXECUTION_TIMEOUT_HOURS", "24"))),
}


def _toposort_tiers(steps: list[dict]) -> list[list[dict]]:
    """Group steps into execution tiers via topological sort.

    Steps with no unmet dependencies go into the earliest tier.
    Returns a list of tiers, each tier being a list of step dicts that
    can execute in parallel.

    Raises ``ValueError`` if the dependency graph has a cycle.
    """
    by_name: dict[str, dict] = {s["name"]: s for s in steps}
    in_degree: dict[str, int] = {s["name"]: 0 for s in steps}
    dependents: dict[str, list[str]] = defaultdict(list)

    for step in steps:
        for dep in step.get("depends_on") or []:
            if dep in by_name:
                in_degree[step["name"]] += 1
                dependents[dep].append(step["name"])

    tiers: list[list[dict]] = []
    queue = deque(name for name, deg in in_degree.items() if deg == 0)
    processed = 0

    while queue:
        tier_names = list(queue)
        queue.clear()
        tiers.append([by_name[n] for n in tier_names])
        processed += len(tier_names)
        for name in tier_names:
            for dep_name in dependents[name]:
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    queue.append(dep_name)

    if processed != len(steps):
        remaining = [n for n, d in in_degree.items() if d > 0]
        raise ValueError(f"Dependency cycle detected among steps: {remaining}")

    return tiers


def _build_dag() -> DAG:
    """Return the dynamic DAG — Airflow picks this up at module level."""
    dag = DAG(
        dag_id=os.getenv("AIRFLOW_DAG_ID", "techneos_airflow_pipeline"),
        default_args=default_args,
        description="Dynamic DAG for TechneOS computational pipelines",
        schedule=None,  # triggered externally only
        start_date=days_ago(1),
        catchup=False,
        is_paused_upon_creation=False,
        max_active_runs=10,
        render_template_as_native_obj=True,
        on_success_callback=on_dag_success,
        on_failure_callback=on_dag_failure,
        params={
            "run_id": "",
            "callback_url": "",
            "callback_token": "",
            "steps": [],
        },
    )

    return dag


# Module-level DAG object — Airflow's DagBag discovers this.
dag = _build_dag()


# ── Pipeline orchestration task ──────────────────────────────────────
# A single Airflow task that handles the full step graph internally.
# This avoids the limitation that Airflow cannot create dynamically-
# named tasks from trigger-time conf.  Steps within the same
# topological tier are dispatched concurrently; tiers run sequentially.
# If any step in a tier fails, remaining tiers are skipped, their
# steps are reported as "skipped", and the task raises so the DAG
# run is marked failed.


@dag.task(task_id="run_pipeline")
def run_pipeline(**context: Any) -> dict[str, Any]:
    """Orchestrate the full step graph respecting depends_on edges."""
    dag_run: DagRun = context["dag_run"]  # type: ignore[assignment]
    conf = dag_run.conf or {}
    run_id: str = conf.get("run_id", "unknown")
    steps = conf.get("steps", [])

    if not steps:
        logger.warning("DAG triggered with empty step list (run_id=%s)", run_id)
        return {"status": "completed", "steps_run": 0}

    # Build execution tiers from dependency graph
    try:
        tiers = _toposort_tiers(steps)
    except ValueError as exc:
        logger.error("Invalid step graph for run %s: %s", run_id, exc)
        raise

    logger.info(
        "Pipeline %s: %d steps in %d tier(s): %s",
        run_id,
        len(steps),
        len(tiers),
        [[s["name"] for s in tier] for tier in tiers],
    )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_execute_tiers(tiers, conf, context))
    finally:
        loop.close()


async def _execute_tiers(
    tiers: list[list[dict]],
    conf: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """Run tiers sequentially; steps within a tier concurrently.

    On failure, remaining tiers are skipped and their steps reported
    as 'skipped' to the platform API.

    On retry, steps that already completed are skipped to avoid
    re-executing work and creating duplicate artifacts.
    """
    from operators.tool_operator import ToolOperator as _Op

    run_id = conf.get("run_id", "unknown")
    callback_url = conf.get("callback_url", "") or os.getenv("PLATFORM_CALLBACK_URL", "")
    callback_token = conf.get("callback_token", "") or os.getenv("INTERNAL_SERVICE_TOKEN", "")

    # On retry, fetch already-completed step names so we can skip them.
    # Also fetch their artifact keys for step-to-step data passing.
    completed_steps, completed_artifacts = await _fetch_completed_steps(
        callback_url, callback_token, run_id
    )

    results: dict[str, str] = {}  # step_name -> "completed" | "failed" | "skipped"
    # Track output artifacts per step for step-to-step data passing.
    # Maps step_name -> list of {"storage_key": ..., "file_name": ...}
    # Pre-populate with artifacts from already-completed steps (retry case)
    step_outputs: dict[str, list[dict[str, str]]] = dict(completed_artifacts)
    failed_step: str | None = None
    failed_error: str | None = None

    for tier_idx, tier in enumerate(tiers):
        if failed_step is not None:
            # Skip remaining tiers — report each step as skipped
            for step in tier:
                logger.info(
                    "Skipping step '%s' (tier %d) — upstream '%s' failed",
                    step["name"],
                    tier_idx,
                    failed_step,
                )
                results[step["name"]] = "skipped"
                await _Op._report_step_status(
                    callback_url,
                    callback_token,
                    run_id,
                    step["name"],
                    "skipped",
                    error_message=f"Skipped: upstream step '{failed_step}' failed",
                )
            continue

        # Inject upstream output references into steps that have depends_on.
        # Tag each artifact with its source step so downstream resolution
        # (both the generic upstream/ download and declared input mappings)
        # can target a specific upstream step.
        for step in tier:
            upstream_outputs: list[dict[str, str]] = []
            for dep_name in step.get("depends_on") or []:
                for art in step_outputs.get(dep_name, []):
                    upstream_outputs.append({**art, "step_name": dep_name})
            if upstream_outputs:
                step["_upstream_outputs"] = upstream_outputs

        # Filter out already-completed steps (relevant on Airflow retry)
        pending_steps = []
        for step in tier:
            if step["name"] in completed_steps:
                logger.info(
                    "Step '%s' (tier %d) already completed — skipping on retry",
                    step["name"],
                    tier_idx,
                )
                results[step["name"]] = "completed"
                continue
            pending_steps.append(step)

        if not pending_steps:
            logger.info("Pipeline %s: tier %d — all steps already completed", run_id, tier_idx)
            continue

        # Run remaining steps in this tier concurrently
        logger.info(
            "Pipeline %s: starting tier %d — %s",
            run_id,
            tier_idx,
            [s["name"] for s in pending_steps],
        )

        operators = []
        for step in pending_steps:
            op = _Op(task_id=f"_internal_{step['name']}", step_conf=step)
            operators.append((step, op))

        tier_tasks = [_run_single_step(op, step, context) for step, op in operators]
        tier_results = await asyncio.gather(*tier_tasks, return_exceptions=True)

        for (step, _op), result in zip(operators, tier_results, strict=True):
            if isinstance(result, Exception):
                results[step["name"]] = "failed"
                if failed_step is None:
                    failed_step = step["name"]
                    failed_error = str(result)
                logger.error("Step '%s' failed: %s", step["name"], result)
            else:
                results[step["name"]] = "completed"
                # Capture output artifact locations for downstream steps
                if isinstance(result, dict) and result.get("artifact_keys"):
                    step_outputs[step["name"]] = result["artifact_keys"]

    if failed_step:
        # If Airflow will retry, overwrite failed/skipped steps to "retrying"
        # so the UI never shows a stale "failed" status during the delay.
        ti = context.get("task_instance")
        max_retries = ti.max_tries if ti else 0
        attempt = ti.try_number if ti else 1
        will_retry = attempt <= max_retries

        if will_retry:
            for step_name, status in results.items():
                if status in ("failed", "skipped"):
                    await _Op._report_step_status(
                        callback_url,
                        callback_token,
                        run_id,
                        step_name,
                        "retrying",
                    )

        raise RuntimeError(f"Pipeline failed at step '{failed_step}': {failed_error}")

    return {"status": "completed", "steps": results}


async def _run_single_step(
    op: ToolOperator,
    step: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """Execute a single ToolOperator step, returning its result."""
    return await op._execute_async(context)


async def _fetch_completed_steps(
    callback_url: str,
    callback_token: str,
    run_id: str,
) -> tuple[set[str], dict[str, list[dict[str, str]]]]:
    """Fetch step names that are already completed for this run.

    Used on Airflow retries to skip re-executing successful steps.
    Returns (completed_step_names, step_artifacts) where step_artifacts
    maps step_name to its artifact keys for downstream data passing.
    Returns empty values on failure (safe default — all steps run).
    """
    if not callback_url:
        return set(), {}
    try:
        url = f"{callback_url}/api/v1/pipeline-runs/{run_id}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"X-Internal-Token": callback_token} if callback_token else {},
            )
            if resp.is_success:
                data = resp.json()
                completed = {
                    s["step_name"] for s in data.get("steps", []) if s.get("status") == "completed"
                }
                # Group artifacts by step_name for data passing
                artifacts_by_step: dict[str, list[dict[str, str]]] = {}
                for a in data.get("artifacts", []):
                    sn = a.get("step_name", "")
                    if sn in completed:
                        artifacts_by_step.setdefault(sn, []).append(
                            {
                                "storage_key": a.get("storage_key", ""),
                                "storage_bucket": a.get("storage_bucket", ""),
                                "file_name": a.get("file_name", ""),
                            }
                        )
                return completed, artifacts_by_step
    except Exception:
        logger.warning("Failed to fetch step statuses for run %s", run_id, exc_info=True)
    return set(), {}


# Instantiate the task so Airflow registers it
run_pipeline()
