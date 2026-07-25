"""Tool-run orchestrator — bridges the tool service API with Airflow.

A tool run is dispatched to the same ``techneos_airflow_pipeline`` DAG that
pipelines use, with ``conf.steps`` set to a one-element list constructed
from the tool's version metadata. ``callback_resource_path`` is included
in the conf so the worker posts status/artifact callbacks back to the
tool service (``/tool-runs/{id}/...``) rather than the pipeline service.

Responsibilities:
1. ``dispatch_tool_run`` — translate a ToolRun + ToolVersion into an
   Airflow DAG trigger conf, call the Airflow API, and update the run
   record with the Airflow references.
2. ``sync_tool_run_status`` — poll Airflow for current state and
   reconcile with the platform database.
3. ``handle_cancel`` — proxy a cancel request to Airflow and update
   the platform record.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from core.airflow.client import AirflowClient, AirflowClientError
from core.airflow.config import AirflowSettings, get_airflow_settings
from core.models.tool import Tool, ToolVersion
from core.models.tool_run import ToolRun
from core.packaging import resolve_package_index_url
from tool_service.events import publish_tool_run_completed, publish_tool_run_failed

logger = logging.getLogger(__name__)


async def dispatch_tool_run(
    session: AsyncSession,
    run: ToolRun,
    tool_version: ToolVersion,
    settings: AirflowSettings | None = None,
    callback_token: str = "",
) -> ToolRun:
    """Trigger an Airflow DAG run for a single-tool execution.

    Builds a one-element ``steps`` conf from the tool version's metadata,
    triggers the shared ``techneos_airflow_pipeline`` DAG, and updates the
    run record with ``airflow_dag_id`` / ``airflow_run_id``.

    If Airflow is not configured, the run is left in ``pending`` status
    for manual / external execution.
    """
    settings = settings or get_airflow_settings()

    if not settings.configured:
        logger.warning(
            "Airflow not configured — tool run %s will remain in 'pending' state.",
            run.id,
        )
        return run

    # Pin the tool-runtime base for pypi tools to the version recorded in the
    # compute-artifact inventory (never a mutable :latest — the worker must run
    # the exact published runtime).
    runtime_image_tag: str | None = None
    tool = tool_version.tool
    if tool and tool.tool_type == "pypi":
        from core.config import get_settings
        from core.database.compute_artifacts import find_latest_artifact

        # The tool-runtime image is recorded under its full name: the ECR URL
        # ({registry}/techneos/tool-runtime) in prod, bare techneos/tool-runtime
        # locally. Query that same name (this is also the ref the worker pulls).
        registry = get_settings().docker_image_registry
        runtime_name = (
            f"{registry}/techneos/tool-runtime" if registry else "techneos/tool-runtime"
        )
        rt = await find_latest_artifact(session, kind="docker_image", name=runtime_name)
        runtime_image_tag = rt.version if rt else None
        if not runtime_image_tag:
            logger.warning(
                "No published %s in the inventory — pypi run %s cannot pin the "
                "runtime image.", runtime_name, run.id,
            )

    step_conf = _build_single_step_conf(
        tool_version, run.parameters or {}, run_id=run.id, runtime_image_tag=runtime_image_tag
    )

    # Inject backend config from the compute_backends table so the worker
    # can pass it to the backend constructor (instead of relying on env vars).
    backend_name = (tool_version.resource_requirements or {}).get("backend")
    if backend_name:
        from core.models.compute_backend import ComputeBackend as CBModel

        cb_result = await session.execute(
            sa_select(CBModel).where(CBModel.name == backend_name)
        )
        cb = cb_result.scalar_one_or_none()
        if cb and cb.config:
            step_conf.setdefault("resource_requirements", {})["backend_config"] = cb.config

    conf: dict[str, Any] = {
        "run_id": run.id,
        "callback_url": settings.platform_callback_url,
        "callback_token": callback_token,
        # Tells the ToolOperator to post status/artifacts to /tool-runs/{id}/...
        "callback_resource_path": "tool-runs",
        "steps": [step_conf],
    }

    dag_id = settings.airflow_dag_id

    async with AirflowClient(settings) as af:
        try:
            dag_run_data = await af.trigger_dag(dag_id, conf=conf)
        except AirflowClientError as exc:
            logger.error("Failed to trigger Airflow DAG for tool run %s: %s", run.id, exc)
            run.status = "failed"
            run.error_message = f"Airflow dispatch failed: {exc}"
            run.finished_at = datetime.now(UTC)
            await session.flush()
            return run

    airflow_run_id = dag_run_data.get("dag_run_id", "")
    run.airflow_dag_id = dag_id
    run.airflow_run_id = airflow_run_id
    run.status = "queued"
    await session.flush()

    logger.info(
        "Dispatched tool run %s → Airflow DAG %s / run %s",
        run.id,
        dag_id,
        airflow_run_id,
    )
    return run


async def sync_tool_run_status(
    session: AsyncSession,
    run: ToolRun,
    settings: AirflowSettings | None = None,
    *,
    force: bool = False,
) -> ToolRun:
    """Poll Airflow and synchronise run status to the database."""
    settings = settings or get_airflow_settings()

    if not run.airflow_dag_id or not run.airflow_run_id:
        return run

    if run.status in ("completed", "failed", "cancelled") and not force:
        return run

    async with AirflowClient(settings) as af:
        try:
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
                    run.error_message = (
                        dag_run_data.get("note")
                        or "Tool run failed — check Airflow task logs for details"
                    )
                logger.info("Tool run %s status updated to %s", run.id, new_status)

                if new_status in ("completed", "failed"):
                    tool_name = "Unknown tool"
                    tool_id = ""
                    try:
                        if run.tool_version and run.tool_version.tool:
                            tool_name = run.tool_version.tool.name
                            tool_id = run.tool_version.tool_id
                        else:
                            tv = await session.get(ToolVersion, run.tool_version_id)
                            if tv:
                                tool_id = tv.tool_id
                                tool = await session.get(Tool, tv.tool_id)
                                if tool:
                                    tool_name = tool.name
                    except Exception:
                        pass

                    # Persist logs to MinIO (fallback if callback path failed)
                    await persist_tool_run_logs(run, session, settings=settings)

                    if new_status == "completed":
                        await publish_tool_run_completed(
                            run_id=run.id,
                            tool_id=tool_id,
                            tool_name=tool_name,
                            submitted_by=run.submitted_by,
                        )
                    else:
                        await publish_tool_run_failed(
                            run_id=run.id,
                            tool_id=tool_id,
                            tool_name=tool_name,
                            submitted_by=run.submitted_by,
                            error=run.error_message,
                        )

        except AirflowClientError as exc:
            logger.warning("Failed to sync tool run %s from Airflow: %s", run.id, exc)

    await session.flush()
    return run


async def handle_cancel(
    session: AsyncSession,
    run: ToolRun,
    settings: AirflowSettings | None = None,
) -> ToolRun:
    """Cancel a run both in Airflow and in the platform database."""
    settings = settings or get_airflow_settings()

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

    run.status = "cancelled"
    run.finished_at = datetime.now(UTC)
    await session.flush()

    logger.info("Cancelled tool run %s", run.id)
    return run


async def persist_tool_run_logs(
    run: ToolRun,
    session: AsyncSession,
    logs_content: str | None = None,
    settings: AirflowSettings | None = None,
) -> str | None:
    """Persist task logs to MinIO for a terminal tool run.

    Combines two complementary sources so the run-detail Logs view shows both
    the actual tool execution and the orchestration context:

    * **Container execution logs** — the tool's own stdout/stderr (for AWS Batch,
      the EC2 container's CloudWatch logs). Sourced from the explicit
      ``logs_content`` (callback payload) or, failing that, ``run.outputs``
      ``logs_tail``.
    * **Orchestration logs** — the Airflow ``run_pipeline`` task log (dispatch,
      S3 staging, artifact collection), fetched via the Airflow REST API.

    Container logs come first because they are what users most often want; the
    Airflow log is appended for context. Sets ``run.log_storage_key`` and flushes
    the session. Returns the storage key, or ``None`` if no logs were available.
    """
    if run.log_storage_key:
        return run.log_storage_key

    slug: str | None = None
    version_no: int | None = None
    tv = getattr(run, "tool_version", None)
    if tv is not None:
        version_no = tv.version
        tool = getattr(tv, "tool", None)
        if tool is not None:
            slug = tool.slug
    if not slug or not version_no:
        logger.warning("Cannot persist logs for run %s: missing slug or version", run.id)
        return None

    # Container execution logs: explicit callback payload, else run.outputs.
    container_logs: str | None = logs_content
    if not container_logs:
        outputs = run.outputs or {}
        for val in outputs.values():
            if isinstance(val, dict) and isinstance(val.get("logs_tail"), str):
                container_logs = val["logs_tail"]
                break
        if not container_logs and isinstance(outputs.get("logs_tail"), str):
            container_logs = outputs["logs_tail"]

    # Orchestration logs: Airflow run_pipeline task log.
    airflow_logs: str | None = None
    if run.airflow_dag_id and run.airflow_run_id:
        try:
            s = settings or get_airflow_settings()
            if s.configured:
                async with AirflowClient(s) as af:
                    airflow_logs = await af.get_task_logs(
                        run.airflow_dag_id,
                        run.airflow_run_id,
                        "run_pipeline",
                        try_number=1,
                    )
                    if airflow_logs:
                        logger.info(
                            "Fetched logs from Airflow for run %s (%d chars)",
                            run.id, len(airflow_logs),
                        )
        except Exception:
            logger.warning("Failed to fetch logs from Airflow for run %s", run.id, exc_info=True)

    sections: list[str] = []
    if container_logs:
        sections.append("=== Container execution logs ===\n" + container_logs)
    if airflow_logs:
        sections.append("=== Orchestration (Airflow) logs ===\n" + airflow_logs)
    log_content: str | None = "\n\n".join(sections) if sections else None

    if not log_content:
        return None

    try:
        import io

        from core.storage import get_object_store

        encoded = log_content.encode("utf-8")
        store = get_object_store()
        log_key = f"tool-runs/{slug}/v{version_no}/{run.id}/logs/stdout.log"
        store.put("techneos-data", log_key, io.BytesIO(encoded), length=len(encoded), content_type="text/plain")
        run.log_storage_key = log_key
        await session.flush()
        logger.info("Persisted %d chars of logs to %s", len(log_content), log_key)
        return log_key
    except Exception:
        logger.exception("Failed to persist logs to MinIO for run %s", run.id)
        return None


# ── Internal helpers ─────────────────────────────────────────────────


def _build_single_step_conf(
    tool_version: ToolVersion,
    parameters: dict[str, Any],
    run_id: str = "",
    runtime_image_tag: str | None = None,
) -> dict[str, Any]:
    """Build the one-element step conf for the techneos_airflow_pipeline DAG."""
    tool = tool_version.tool
    tool_slug = tool.slug if tool else ""
    tool_type = tool.tool_type if tool else "container"

    # Image conventions mirror the pipeline orchestrator:
    # techneos/{slug} for container tools, empty for pypi (worker installs the
    # package) and human (no container).
    image = "" if tool_type in ("pypi", "human") else f"techneos/{tool_slug}" if tool_slug else ""

    container_cfg = getattr(tool_version, "container_config", None)
    if container_cfg and container_cfg.docker_image:
        image = container_cfg.docker_image
    # Container tools pin via their recorded docker_tag; pypi tools pin the
    # tool-runtime base to the version resolved from the inventory. Never :latest.
    image_tag = (container_cfg.docker_tag if container_cfg else None) or runtime_image_tag or "latest"

    # Property names declared in the tool's input_schema. The worker uses
    # this list to know which parameter keys may carry a dataset/upload
    # reference and should be resolved into local files; values that
    # aren't references pass through to params.json untouched so tools
    # can still accept inline data.
    input_schema = tool_version.input_schema or {}
    input_keys = list((input_schema.get("properties") or {}).keys())
    # Tool-wide input contract, e.g. "smiles_list" — declared once at the
    # top of input_schema. The worker copies this into inputs.json so the
    # runtime preprocessor picks the right parser/standardizer. May be
    # None for legacy tools that haven't been re-registered yet; the
    # runtime falls back to its registry default in that case.
    input_kind = input_schema.get("input_kind") if isinstance(input_schema, dict) else None

    # Auto-detect smiles_list_key: the first array property in input_schema.
    # This tells the tool which key to read from input_data (e.g. "compounds"
    # instead of the default "smiles"). Detected automatically so callers
    # (including pipelines) don't need to set it manually.
    if input_kind == "smiles_list":
        props = (input_schema.get("properties") or {}) if isinstance(input_schema, dict) else {}
        for key, prop in props.items():
            if isinstance(prop, dict) and prop.get("type") == "array":
                parameters.setdefault("smiles_list_key", key)
                break

    # Artifact key prefix: tool-runs/{slug}/v{N}/{run_id}/output. The worker
    # uses this as the storage-key prefix for output artifacts. Inputs land
    # under the sibling `.../input/` prefix at bind time (see submit_run),
    # so the full per-run layout in MinIO is:
    #   tool-runs/{slug}/v{N}/{run_id}/input/<file>
    #   tool-runs/{slug}/v{N}/{run_id}/output/<file>
    key_prefix = ""
    if tool_slug and run_id:
        key_prefix = f"tool-runs/{tool_slug}/v{tool_version.version}/{run_id}/output"

    conf: dict[str, Any] = {
        "name": tool_slug or "tool-run",
        "tool_slug": tool_slug,
        "tool_version": tool_version.version,
        "tool_type": tool_type,
        "image": image,
        "image_tag": image_tag,
        "command": None,
        "parameters": parameters,
        "resource_requirements": tool_version.resource_requirements or {},
        "depends_on": [],
        "inputs": {},
        "input_keys": input_keys,
        "input_kind": input_kind,
        "key_prefix": key_prefix,
    }

    if tool_type == "pypi":
        pypi = getattr(tool_version, "pypi_config", None)
        conf["package_name"] = pypi.package_name if pypi else None
        conf["package_version"] = pypi.package_version if pypi else None
        conf["entry_point"] = pypi.entry_point if pypi else None
        # Per-tool override → PYTHON_PACKAGE_INDEX_URL env var, rewritten so
        # a spawned tool container can reach a host-mapped index. Shared with
        # the pipeline orchestrator via core.packaging.
        per_tool_url = pypi.package_index_url if pypi else None
        conf["package_index_url"] = resolve_package_index_url(per_tool_url)

    elif tool_type == "human":
        human_cfg = getattr(tool_version, "human_config", None)
        conf["human_config"] = {
            "assignment_type": human_cfg.assignment_type if human_cfg else "team",
            "default_user_email": human_cfg.default_user_email if human_cfg else None,
            "default_team_slug": human_cfg.default_team_slug if human_cfg else None,
            # Legacy convenience field — derived from the split columns.
            "default_assignee": human_cfg.default_assignee if human_cfg else None,
            "due_in_hours": human_cfg.due_in_hours if human_cfg else 72,
            "require_attachments": human_cfg.require_attachments if human_cfg else False,
            "default_project_lead_email": human_cfg.default_project_lead_email
            if human_cfg
            else None,
            "priority": human_cfg.priority if human_cfg else "medium",
            "title": f"{tool.name}: {run_id[:8]}" if tool else f"Assignment: {run_id[:8]}",
        }
        # Add the tool version's input/output schemas so the frontend can render
        # the submission form
        conf["input_schema"] = tool_version.input_schema or {}
        conf["output_schema"] = tool_version.output_schema or {}

    return conf
