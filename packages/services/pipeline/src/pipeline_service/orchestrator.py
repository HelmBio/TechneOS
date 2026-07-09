"""Pipeline orchestrator — bridges the pipeline service API with Airflow.

Responsibilities:
1. **dispatch_run** — translate a PipelineRun + Pipeline into
   an Airflow DAG trigger conf, call the Airflow API, and update the
   run record with the Airflow references.
2. **sync_run_status** — poll Airflow for the current state of a run
   and its task instances, then reconcile with the platform database.
3. **handle_cancel** — proxy a cancel request to Airflow and update
   the platform record.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from core.airflow.client import AirflowClient, AirflowClientError
from core.airflow.config import AirflowSettings, get_airflow_settings
from core.config import get_settings
from core.models.pipeline import Pipeline, PipelineRun, PipelineStepRun, PipelineVersion
from core.packaging import resolve_package_index_url
from core.pipeline_topology import merge
from pipeline_service.crud.runs import get_step_runs, update_step_run
from pipeline_service.events import publish_pipeline_run_completed, publish_pipeline_run_failed

logger = logging.getLogger(__name__)


async def dispatch_run(
    session: AsyncSession,
    run: PipelineRun,
    definition: PipelineVersion,
    settings: AirflowSettings | None = None,
    callback_token: str = "",
) -> PipelineRun:
    """Trigger an Airflow DAG run for a pipeline run.

    Builds the ``conf`` dict from the pipeline definition and run
    parameters, triggers the DAG, and updates the run record with
    ``airflow_dag_id`` and ``airflow_run_id``.

    If Airflow is not configured (``airflow_base_url`` is empty),
    the run is left in ``pending`` status — useful for local
    development where an external poller or manual testing handles
    execution.
    """
    settings = settings or get_airflow_settings()

    if not settings.configured:
        logger.warning(
            "Airflow not configured — run %s will remain in 'pending' state. "
            "Set AIRFLOW_BASE_URL to enable orchestration.",
            run.id,
        )
        return run

    # Resolve the pipeline definition for slug-based artifact prefixing.
    # ``definition`` here is actually a PipelineVersion (param misnamed).
    pipeline_def = getattr(definition, "pipeline", None) or await session.get(
        Pipeline, definition.pipeline_id
    )
    pipeline_slug = pipeline_def.slug if pipeline_def else ""

    # Build step configs for the Airflow DAG
    step_confs = await _build_step_confs(
        definition,
        run,
        pipeline=pipeline_def,
        pipeline_slug=pipeline_slug,
        pipeline_version_num=definition.version,
    )

    # Inject backend_config from compute_backends table for each step that
    # specifies a backend, so the worker can pass DB-stored config to the
    # backend constructor.
    backend_names = {
        sc.get("resource_requirements", {}).get("backend")
        for sc in step_confs
        if sc.get("resource_requirements", {}).get("backend")
    }
    if backend_names:
        from core.models.compute_backend import ComputeBackend as CBModel

        cb_result = await session.execute(
            sa_select(CBModel).where(CBModel.name.in_(backend_names))
        )
        cb_map = {cb.name: cb.config for cb in cb_result.scalars().all() if cb.config}
        for sc in step_confs:
            bn = sc.get("resource_requirements", {}).get("backend")
            if bn and bn in cb_map:
                sc["resource_requirements"]["backend_config"] = cb_map[bn]

    conf: dict[str, Any] = {
        "run_id": run.id,
        "callback_url": settings.platform_callback_url,
        "callback_token": callback_token,
        "steps": step_confs,
    }

    dag_id = settings.airflow_dag_id

    async with AirflowClient(settings) as af:
        try:
            dag_run_data = await af.trigger_dag(dag_id, conf=conf)
        except AirflowClientError as exc:
            logger.error("Failed to trigger Airflow DAG for run %s: %s", run.id, exc)
            run.status = "failed"
            run.error_message = f"Airflow dispatch failed: {exc}"
            run.finished_at = datetime.now(UTC)
            await session.flush()
            return run

    # Update run with Airflow references
    airflow_run_id = dag_run_data.get("dag_run_id", "")
    run.airflow_dag_id = dag_id
    run.airflow_run_id = airflow_run_id
    run.status = "queued"
    await session.flush()

    logger.info(
        "Dispatched run %s → Airflow DAG %s / run %s",
        run.id,
        dag_id,
        airflow_run_id,
    )
    return run


async def sync_run_status(
    session: AsyncSession,
    run: PipelineRun,
    settings: AirflowSettings | None = None,
    *,
    force: bool = False,
) -> PipelineRun:
    """Poll Airflow and synchronise run + step statuses to the database.

    Call this periodically (e.g. from a background task or a dedicated
    ``/runs/{id}/sync`` endpoint) to keep the platform in sync with
    Airflow's actual execution state.

    Set *force=True* to re-sync step statuses even when the run is
    already in a terminal state (useful if steps were never synced).
    """
    settings = settings or get_airflow_settings()

    if not run.airflow_dag_id or not run.airflow_run_id:
        return run

    if run.status in ("completed", "failed", "cancelled") and not force:
        return run

    async with AirflowClient(settings) as af:
        try:
            # Sync overall run status
            dag_run_data = await af.get_dag_run(run.airflow_dag_id, run.airflow_run_id)
            new_status = AirflowClient.map_dag_run_state(dag_run_data.get("state", "queued"))

            old_status = run.status
            if new_status != old_status:
                run.status = new_status
                if new_status == "running" and run.started_at is None:
                    run.started_at = datetime.now(UTC)
                if new_status in ("completed", "failed"):
                    run.finished_at = datetime.now(UTC)
                if new_status == "failed" and not run.error_message:
                    # Try to capture error note from Airflow dag run
                    run.error_message = (
                        dag_run_data.get("note")
                        or "Pipeline failed — check Airflow task logs for details"
                    )
                logger.info("Run %s status updated to %s", run.id, new_status)

                # Publish notification events on terminal transitions
                if new_status in ("completed", "failed"):
                    # Resolve pipeline name via version -> definition
                    pipeline_name = "Unknown pipeline"
                    pipeline_id = None
                    try:
                        if run.version and run.version.pipeline:
                            pipeline_name = run.version.pipeline.name
                            pipeline_id = run.version.pipeline_id
                        else:
                            from core.models.pipeline import PipelineVersion as PV  # noqa: N817

                            pv = await session.get(PV, run.version_id)
                            if pv:
                                pipeline_id = pv.pipeline_id
                                defn = await session.get(Pipeline, pv.pipeline_id)
                                if defn:
                                    pipeline_name = defn.name
                    except Exception:
                        pass
                    if new_status == "completed":
                        await publish_pipeline_run_completed(
                            run_id=run.id,
                            pipeline_id=pipeline_id or "",
                            pipeline_name=pipeline_name,
                            submitted_by=run.submitted_by,
                        )
                    else:
                        await publish_pipeline_run_failed(
                            run_id=run.id,
                            pipeline_id=pipeline_id or "",
                            pipeline_name=pipeline_name,
                            submitted_by=run.submitted_by,
                            error=run.error_message,
                        )

            # Sync step statuses from task instances
            task_instances = await af.get_task_instances(run.airflow_dag_id, run.airflow_run_id)
            await _sync_step_statuses(session, run, task_instances)

        except AirflowClientError as exc:
            logger.warning("Failed to sync run %s from Airflow: %s", run.id, exc)

    await session.flush()
    return run


async def handle_cancel(
    session: AsyncSession,
    run: PipelineRun,
    settings: AirflowSettings | None = None,
) -> PipelineRun:
    """Cancel a run both in the platform database and in Airflow."""
    settings = settings or get_airflow_settings()

    # Cancel in Airflow if we have a reference
    if run.airflow_dag_id and run.airflow_run_id and settings.configured:
        async with AirflowClient(settings) as af:
            try:
                await af.cancel_dag_run(run.airflow_dag_id, run.airflow_run_id)
            except AirflowClientError as exc:
                logger.warning(
                    "Failed to cancel Airflow run %s/%s: %s",
                    run.airflow_dag_id,
                    run.airflow_run_id,
                    exc,
                )

    # Cancel any non-terminal steps
    now = datetime.now(UTC)
    step_runs = await get_step_runs(session, str(run.id))
    for sr in step_runs:
        if sr.status in ("pending", "running", "retrying"):
            await update_step_run(session, str(sr.id), status="cancelled", finished_at=now)

    # Update platform record
    run.status = "cancelled"
    run.finished_at = now
    await session.flush()

    logger.info("Cancelled run %s", run.id)
    return run


# ── Internal helpers ─────────────────────────────────────────────────


async def _build_step_confs(
    definition: PipelineVersion,
    run: PipelineRun,
    *,
    pipeline: Pipeline | None = None,
    pipeline_slug: str = "",
    pipeline_version_num: int | None = None,
) -> list[dict[str, Any]]:
    """Convert pipeline definition steps into Airflow-friendly conf dicts.

    Each step conf includes all information the ``ToolOperator`` needs
    to dispatch a job to the appropriate compute backend.

    The executable steps are reconstructed by merging the parent
    pipeline's canonical **shape** (``pipeline.steps``) with this version's
    per-step **bindings** (``definition.bindings``: ``tool_version`` +
    ``parameters``).

    For pypi-type tools, fetches package fields (package_name,
    package_version, entry_point, package_index_url) from the tool service
    if they aren't already on the step definition. Module-type tools are not supported; any module fields on a step's
    JSON are ignored.
    """
    shape_steps = pipeline.steps if pipeline is not None else []
    steps: list[dict[str, Any]] = merge(shape_steps, definition.bindings or {})
    merged_params = run.parameters or {}
    step_names = {s.get("name", "") for s in steps}
    result = []

    # Cache tool details to avoid duplicate fetches
    _tool_cache: dict[str, dict[str, Any]] = {}

    for step in steps:
        step_params = {**step.get("parameters", {})}
        # Apply run-level parameters to every step.  Namespaced params
        # (e.g. "predict_admet.endpoints") are applied only to the
        # matching step with the prefix stripped.  Non-namespaced params
        # (e.g. "smiles") are applied to all steps as defaults (step-
        # level values take precedence).
        step_name = step.get("name", "")
        for k, v in merged_params.items():
            if k.startswith(f"{step_name}."):
                # Namespaced: "predict_admet.endpoints" → "endpoints"
                stripped = k[len(step_name) + 1 :]
                step_params[stripped] = v
            elif "." in k and k.split(".", 1)[0] in step_names:
                # Namespaced for a *different* step — don't leak it here.
                continue
            elif k not in step_params:
                # Global param — apply as default if step doesn't override
                step_params[k] = v

        tool_slug = step.get("tool_slug", "")
        tool_type = step.get("tool_type", "")

        # Package-based tool fields (pypi type)
        package_name = step.get("package_name")
        package_version = step.get("package_version")
        entry_point = step.get("entry_point")
        package_index_url = step.get("package_index_url")

        # Human tool fields (resolved from tool version data)
        human_config = step.get("human_config")
        human_input_schema = step.get("input_schema")
        human_output_schema = step.get("output_schema")

        # Container image fields (resolved from tool version data). The version
        # row stores the full image reference — in prod the ECR URL the worker
        # must pull (the host's ECR credential helper authenticates it); a bare
        # techneos/<slug> would resolve to Docker Hub and 404.
        registry_image = step.get("image")
        registry_image_tag = step.get("image_tag")

        # Resolve tool details from the tool service when tool_type is missing,
        # when pypi/human tools need version data, or when a container tool has
        # no explicit image pinned on the step (so we can read its ECR URL).
        needs_fetch = tool_slug and (
            not tool_type
            or (tool_type == "pypi" and not package_name)
            or tool_type == "human"
            or (tool_type == "container" and not registry_image)
        )
        if needs_fetch:
            tool_data = await _fetch_tool_details(tool_slug, _tool_cache)
            if tool_data:
                tool_type = tool_type or tool_data.get("tool_type", "container")
                version_data = tool_data.get("_active_version", {})

                # Pypi package fields
                package_name = package_name or version_data.get("package_name")
                package_version = package_version or version_data.get("package_version")
                entry_point = entry_point or version_data.get("entry_point")
                package_index_url = package_index_url or version_data.get("package_index_url")

                # Container image coordinates (docker_image is the ECR URL in prod)
                registry_image = registry_image or version_data.get("docker_image")
                registry_image_tag = registry_image_tag or version_data.get("docker_tag")

                # Human config fields — stored on the active version
                if tool_type == "human" and version_data:
                    human_config = human_config or version_data.get("human_config") or {}
                    human_input_schema = (
                        human_input_schema or version_data.get("input_schema") or {}
                    )
                    human_output_schema = (
                        human_output_schema or version_data.get("output_schema") or {}
                    )

        # Default to container if still unresolved
        tool_type = tool_type or "container"

        # Image resolution order: explicit step/version image (the stored ECR URL
        # in prod) → derived techneos/<slug> fallback. Pypi and human tools need no
        # image — pypi installs into techneos/tool-runtime, human tools have no container.
        if tool_type in ("pypi", "human"):
            image = ""
        elif registry_image:
            image = registry_image
        else:
            image = f"techneos/{tool_slug}" if tool_slug else ""
        image_tag = registry_image_tag or "latest"
        if tool_type == "human":
            image_tag = ""

        # Artifact key prefix: pipeline-runs/{slug}/v{N}/{run_id}/{step_name}.
        # The worker uses this as the storage-key prefix for output
        # artifacts. Falls back to empty when slug or version is missing —
        # upload_artifact uses its legacy {run_id}/{step_name} layout in
        # that case.
        if pipeline_slug and pipeline_version_num is not None:
            key_prefix = (
                f"pipeline-runs/{pipeline_slug}/v{pipeline_version_num}/{run.id}/{step_name}"
            )
        else:
            key_prefix = ""

        conf = {
            "name": step.get("name", "unnamed"),
            "tool_slug": tool_slug,
            "tool_version": step.get("tool_version"),
            "tool_type": tool_type,
            "image": image,
            "image_tag": image_tag,
            "command": step.get("command"),
            "parameters": step_params,
            "resource_requirements": step.get("resource_requirements", {}),
            "depends_on": step.get("depends_on", []),
            "inputs": step.get("inputs", {}),
            "key_prefix": key_prefix,
        }

        # Type-specific fields — pypi carries package coords; container/api
        # rely on image + image_tag set above.
        if tool_type == "pypi":
            conf["package_name"] = package_name
            conf["package_version"] = package_version
            conf["entry_point"] = entry_point
            # Per-tool override (rarely set) → PYTHON_PACKAGE_INDEX_URL env,
            # rewritten for the tool container. Mirrors the tool-service
            # orchestrator so pipeline-run installs use the same index as
            # direct tool-runs (otherwise the empty per-tool URL yields no
            # --index-url and the worker falls back to public PyPI).
            conf["package_index_url"] = resolve_package_index_url(package_index_url)

        elif tool_type == "human":
            conf["human_config"] = human_config or {}
            conf["input_schema"] = human_input_schema or {}
            conf["output_schema"] = human_output_schema or {}
            # Pass the resolved version id so HumanBackend can hand it to
            # task-service. Falls back to whatever was already on the step
            # (set by the pipeline definition) — the active-version lookup
            # in _fetch_tool_details runs above.
            if needs_fetch:
                tool_data = _tool_cache.get(tool_slug) or {}
                version_data = tool_data.get("_active_version") or {}
                resolved_version_id = version_data.get("id")
                if resolved_version_id:
                    conf["tool_version_id"] = resolved_version_id

        result.append(conf)

    return result


async def _fetch_tool_details(
    tool_slug: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Fetch tool + active version details from the tool service.

    Results are cached in ``cache`` to avoid duplicate HTTP calls within
    a single dispatch.
    """
    if tool_slug in cache:
        return cache[tool_slug]

    try:
        settings = get_settings()
        url = f"{settings.tool_service_url}{settings.api_v1_prefix}/tools/by-slug/{tool_slug}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning(
                "Failed to fetch tool details for slug '%s': %s %s",
                tool_slug,
                resp.status_code,
                resp.text[:200],
            )
            cache[tool_slug] = {}
            return None

        data = resp.json()
        # Find the active version (or latest)
        versions = data.get("versions", [])
        active = next((v for v in versions if v.get("status") == "active"), None)
        if not active and versions:
            active = versions[0]  # versions are returned newest-first
        data["_active_version"] = active or {}
        cache[tool_slug] = data
        return cast(dict[str, Any] | None, data)
    except Exception:
        logger.warning("Error fetching tool details for '%s'", tool_slug, exc_info=True)
        cache[tool_slug] = {}
        return None


async def _sync_step_statuses(
    session: AsyncSession,
    run: PipelineRun,
    task_instances: list[dict[str, Any]],
) -> None:
    """Reconcile Airflow task instance states with platform step runs."""
    step_runs = await get_step_runs(session, run.id)
    step_map: dict[str, PipelineStepRun] = {sr.step_name: sr for sr in step_runs}

    for ti in task_instances:
        task_id = ti.get("task_id", "")
        af_state = ti.get("state", "queued")
        platform_status = AirflowClient.map_task_state(af_state)

        # The DAG now uses a single "run_pipeline" task that orchestrates
        # all steps internally.  Individual step statuses are reported
        # directly via the callback endpoint, so the sync here only
        # handles the top-level run_pipeline task → overall run status.
        #
        # For the legacy "run_tool_step" mapped-task DAG, try to extract
        # the step name from rendered_fields.step_conf.name.
        rendered = ti.get("rendered_fields", {})
        step_conf = rendered.get("step_conf") if isinstance(rendered, dict) else None
        step_name_from_conf = step_conf.get("name", "") if isinstance(step_conf, dict) else ""

        # Try matching: rendered step_conf name first, then task_id, then partial
        matched_step = step_map.get(step_name_from_conf)
        if matched_step is None:
            matched_step = step_map.get(task_id)
        if matched_step is None:
            for name, sr in step_map.items():
                if name in task_id or task_id in name:
                    matched_step = sr
                    break

        if matched_step is None:
            # For the "run_pipeline" task, there's no 1:1 step mapping.
            # Step statuses are updated via direct callbacks from the
            # ToolOperator, so we skip unmatched task instances.
            continue

        if matched_step.status == platform_status:
            continue

        started = None
        finished = None
        error_msg = None
        if platform_status == "running" and matched_step.started_at is None:
            started = datetime.now(UTC)
        if platform_status in ("completed", "failed", "skipped"):
            finished = datetime.now(UTC)
        if platform_status == "failed":
            error_msg = (
                ti.get("note")
                or ti.get("rendered_fields", {}).get("error")
                or "Task failed — check Airflow logs"
            )

        await update_step_run(
            session,
            matched_step.id,
            status=platform_status,
            error_message=error_msg,
            started_at=started,
            finished_at=finished,
        )
