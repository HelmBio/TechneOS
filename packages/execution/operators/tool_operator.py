"""ToolOperator — Airflow operator that dispatches a pipeline step to a compute backend.

Each instance of this operator handles a single step in the pipeline.
It resolves the appropriate compute backend (Docker, AWS Batch) from
the step's resource requirements, submits the job, polls until
completion, collects output artifacts, uploads them to MinIO, and
reports status back to the platform API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from airflow.models import BaseOperator
from backends.aws_batch_backend import AWSBatchBackend
from backends.base import ComputeBackend, JobResult, JobSpec, JobStatus
from backends.docker_backend import DockerBackend
from backends.human_backend import HumanBackend
from backends.slurm_backend import SlurmBackend

# Shared temp directory for dataset downloads.  When running inside the
# Airflow scheduler container the default /tmp is container-local and
# invisible to sibling Docker containers.  TECHNEOS_SHARED_INPUT_DIR points
# to a bind-mounted directory that both the scheduler and tool containers
# can access.  TECHNEOS_HOST_SHARED_INPUT_DIR is the corresponding *host*
# path — needed because Docker bind-mounts are resolved on the host.
_SHARED_INPUT_DIR = os.environ.get("TECHNEOS_SHARED_INPUT_DIR", "")
_HOST_SHARED_INPUT_DIR = os.environ.get("TECHNEOS_HOST_SHARED_INPUT_DIR", "")

logger = logging.getLogger(__name__)

# Poll interval in seconds when waiting for a job to finish
_POLL_INTERVAL = int(os.getenv("TOOL_OPERATOR_POLL_INTERVAL", "15"))
_POLL_TIMEOUT = int(os.getenv("TOOL_OPERATOR_POLL_TIMEOUT", "86400"))  # 24h


def _get_backend(name: str, config: dict | None = None) -> ComputeBackend:
    """Instantiate a compute backend by name.

    When *config* is provided (from the compute_backends DB table via the
    DAG conf), it is passed as kwargs to the backend constructor.  This
    lets the platform push per-backend settings (job queue, SSH host, etc.)
    without relying solely on environment variables.
    """
    backends: dict[str, type[ComputeBackend]] = {
        "docker": DockerBackend,
        "aws_batch": AWSBatchBackend,
        "slurm": SlurmBackend,
        "human": HumanBackend,
    }
    default = os.getenv("COMPUTE_BACKEND", "docker")
    backend_cls = backends.get(name, backends.get(default, DockerBackend))
    return backend_cls(**config) if config else backend_cls()


class ToolOperator(BaseOperator):
    """Execute a single pipeline step via a compute backend.

    Parameters
    ----------
    step_conf : dict
        Step configuration from the DAG trigger conf.  Expected keys:
        ``name``, ``image``, ``image_tag``, ``parameters``,
        ``resource_requirements``, ``tool_slug``, ``tool_version``.
    """

    template_fields = ("step_conf",)

    def __init__(self, step_conf: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.step_conf = step_conf or {}

    def execute(self, context: Any) -> dict[str, Any]:
        """Run the tool step synchronously (Airflow manages the async loop)."""
        import asyncio

        return asyncio.get_event_loop().run_until_complete(self._execute_async(context))

    async def _execute_async(self, context: Any) -> dict[str, Any]:
        dag_run = context["dag_run"]
        conf = dag_run.conf or {}
        run_id: str = conf.get("run_id", "unknown")
        callback_url: str = conf.get("callback_url", "") or os.getenv("PLATFORM_CALLBACK_URL", "")
        callback_token: str = conf.get("callback_token", "") or os.getenv(
            "INTERNAL_SERVICE_TOKEN", ""
        )
        # Resource segment under /api/v1 — "pipeline-runs" (default) for
        # pipeline executions, "tool-runs" for standalone tool runs.
        callback_resource_path: str = conf.get("callback_resource_path", "pipeline-runs")

        step = self.step_conf
        step_name: str = step.get("name", "unnamed")
        resources = step.get("resource_requirements", {})
        tool_type: str = step.get("tool_type", "container")

        logger.info(
            "ToolOperator: starting step '%s' (type=%s) for run %s",
            step_name,
            tool_type,
            run_id,
        )

        # Report step as running
        await self._report_step_status(
            callback_url,
            callback_token,
            run_id,
            step_name,
            "running",
            resource_path=callback_resource_path,
        )

        # ── Select execution path ──────────────────────────────────────
        # human:   No container — creates a TaskRun in task-service and polls.
        # runtime: Every other tool. The tool reads /work/inputs.json +
        #          /work/params.json via techneos-tool-runtime; the worker
        #          bind-mounts the whole host work dir at /work and reads
        #          outputs back from there directly (no docker cp).
        if tool_type == "human":
            spec = await self._build_human_spec(
                step=step,
                step_name=step_name,
                run_id=run_id,
                resources=resources,
                callback_url=callback_url,
                callback_token=callback_token,
            )
            backend_name = "human"
        else:
            spec = await self._build_runtime_spec(
                step=step,
                step_name=step_name,
                run_id=run_id,
                resources=resources,
                callback_url=callback_url,
                callback_token=callback_token,
            )
            backend_name = resources.get("backend", os.getenv("COMPUTE_BACKEND", "docker"))
        backend_config = resources.get("backend_config")
        backend = _get_backend(backend_name, config=backend_config)

        # Submit
        try:
            job_id = await backend.submit_job(spec)
            logger.info("Submitted job %s for step '%s'", job_id, step_name)
        except Exception as exc:
            await self._report_step_status(
                callback_url,
                callback_token,
                run_id,
                step_name,
                "failed",
                error_message=str(exc),
                resource_path=callback_resource_path,
            )
            raise

        # Poll until done
        elapsed = 0
        result = None
        while elapsed < _POLL_TIMEOUT:
            result = await backend.get_job_status(job_id)
            if result.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                break

            # Check if the platform cancelled the run
            if await self._is_run_cancelled(
                callback_url, callback_token, run_id, callback_resource_path,
            ):
                logger.info("Run %s was cancelled — stopping container %s", run_id, job_id)
                await backend.cancel_job(job_id)
                result = JobResult(job_id=job_id, status=JobStatus.CANCELLED)
                break

            interval = (
                result.extra.get("poll_interval_hint", _POLL_INTERVAL)
                if result.extra
                else _POLL_INTERVAL
            )
            interval = max(interval, 10)  # floor 10s
            await asyncio.sleep(interval)
            elapsed += interval

        if result is None or result.status == JobStatus.FAILED:
            error = result.error_message if result else "Poll timeout"
            await self._report_step_status(
                callback_url,
                callback_token,
                run_id,
                step_name,
                "failed",
                error_message=error,
                resource_path=callback_resource_path,
            )
            raise RuntimeError(f"Step '{step_name}' failed: {error}")

        if result.status == JobStatus.CANCELLED:
            try:
                await backend.cleanup_container(job_id)
            except Exception:
                logger.debug("Container cleanup failed for %s", job_id)
            if spec.work_dir_host:
                _cleanup_work_dir(spec.work_dir_host)
            await self._report_step_status(
                callback_url,
                callback_token,
                run_id,
                step_name,
                "skipped",
                resource_path=callback_resource_path,
            )
            return {"status": "cancelled"}

        if elapsed >= _POLL_TIMEOUT and result.status not in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            await backend.cancel_job(job_id)
            await self._report_step_status(
                callback_url,
                callback_token,
                run_id,
                step_name,
                "failed",
                error_message="Timed out",
                resource_path=callback_resource_path,
            )
            raise RuntimeError(f"Step '{step_name}' timed out after {_POLL_TIMEOUT}s")

        # Collect logs
        logs = await backend.get_logs(job_id, tail=5000)

        # ── Artifact collection ─────────────────────────────────────
        artifact_ids: list[str] = []
        artifact_keys: list[dict[str, str]] = []
        try:
            output_files = await backend.collect_outputs(
                job_id,
                work_dir_host=spec.work_dir_host,
            )
            if output_files:
                artifact_ids, artifact_keys = await self._upload_and_register_artifacts(
                    run_id=run_id,
                    step_name=step_name,
                    files=output_files,
                    callback_url=callback_url,
                    callback_token=callback_token,
                    resource_path=callback_resource_path,
                    key_prefix=step.get("key_prefix") or None,
                )
                logger.info(
                    "Registered %d artifact(s) for step '%s'",
                    len(artifact_ids),
                    step_name,
                )
        except Exception:
            logger.exception("Artifact collection failed for step '%s'", step_name)
            # Non-fatal — step still succeeds even if artifacts fail

        # Clean up container
        try:
            await backend.cleanup_container(job_id)
        except Exception:
            logger.debug("Container cleanup failed for %s", job_id)

        # Clean up the per-step work dir (bind-mounted at /work).
        if spec.work_dir_host:
            _cleanup_work_dir(spec.work_dir_host)

        # Report success
        await self._report_step_status(
            callback_url,
            callback_token,
            run_id,
            step_name,
            "completed",
            outputs={"logs_tail": logs, "job_id": job_id, "artifact_ids": artifact_ids},
            resource_path=callback_resource_path,
        )

        logger.info("Step '%s' completed successfully (job %s)", step_name, job_id)
        return {
            "status": "completed",
            "job_id": job_id,
            "artifacts": len(artifact_ids),
            "artifact_keys": artifact_keys,
        }

    # ── JobSpec builders (container/pypi vs. human) ─────────────────

    async def _build_runtime_spec(
        self,
        *,
        step: dict[str, Any],
        step_name: str,
        run_id: str,
        resources: dict[str, Any],
        callback_url: str,
        callback_token: str,
    ) -> JobSpec:
        """Build a JobSpec for a container/pypi tool (techneos-tool-runtime).

        Lays out a /work/ directory on the host with:
            /work/inputs.json   — resolved input file paths + upstream artifacts
            /work/params.json   — step parameters (verbatim)
            /work/input/        — dataset files + upstream artifacts (downloaded)
            /work/output/       — empty; tool writes here

        The backend bind-mounts the whole dir to /work in the container.
        """
        parameters = step.get("parameters", {})
        tool_type = step.get("tool_type", "container")
        tool_slug = step.get("tool_slug", "")

        # Build the host work directory layout.
        work_dir_host = _make_shared_tmpdir(prefix=f"techneos-work-{step_name}-")
        wd = Path(work_dir_host)
        (wd / "input").mkdir(parents=True, exist_ok=True)
        (wd / "output").mkdir(parents=True, exist_ok=True)

        inputs_payload: dict[str, Any] = {}

        # Tool-wide input contract from the tool version's input_schema —
        # the runtime preprocessor uses this to pick the parser and to
        # decide whether the optional standardize block applies. Underscore
        # prefix marks it as platform metadata rather than tool data.
        if step.get("input_kind"):
            inputs_payload["_input_kind"] = step["input_kind"]

        # ── Datasets: resolve refs → download into /work/input/ ──
        dataset_files = await self._resolve_datasets_into_workdir(
            parameters,
            wd,
            callback_url,
            callback_token,
            input_keys=step.get("input_keys") or [],
        )
        inputs_payload.update(dataset_files)

        # ── Upstream artifacts: download into /work/input/upstream/{step}/ ──
        upstream_files = self._resolve_upstream_into_workdir(step, wd)
        if upstream_files:
            inputs_payload["upstream"] = upstream_files
            # Convenience: a flat list, matching report-generator's preferred shape.
            inputs_payload.setdefault(
                "upstream_csvs",
                [
                    p
                    for paths in upstream_files.values()
                    for p in paths
                    if p.lower().endswith((".csv", ".tsv"))
                ],
            )

        # ── Declared inputs: map a named tool input field to an upstream
        #    step's output (path + filter) → inputs.json[field]. This is the
        #    general way downstream tools consume upstream data. ──
        declared_inputs = self._resolve_declared_inputs(step, wd)
        inputs_payload.update(declared_inputs)

        # Write the JSON sidecars.
        (wd / "inputs.json").write_text(json.dumps(inputs_payload, default=str))
        (wd / "params.json").write_text(json.dumps(parameters, default=str))

        # ── Image + command ─────────────────────────────────────────
        env = {
            "TECHNEOS_RUN_ID": run_id,
            "TECHNEOS_STEP_NAME": step_name,
            "TECHNEOS_CALLBACK_URL": callback_url,
            "TECHNEOS_WORK_DIR": "/work",
        }

        if tool_type == "container":
            image = step.get("image") or (f"techneos/{tool_slug}" if tool_slug else "")
            image_tag = step.get("image_tag", "latest")
            if not image:
                raise ValueError(
                    f"Container step '{step_name}' has no image (set 'image' "
                    "or 'tool_slug' so it can be derived as techneos/{slug})."
                )
            # Image's ENTRYPOINT is `python -m techneos_tool_runtime.runner`; no
            # command override needed. The tool's ENTRYPOINT_SPEC env baked
            # into the image picks the right run() function.
            command: list[str] | None = step.get("command")
        elif tool_type == "pypi":
            package_name = step.get("package_name")
            package_version = step.get("package_version")
            entry_point = step.get("entry_point")
            package_index_url = step.get("package_index_url", "") or ""
            if not all([package_name, package_version, entry_point]):
                raise ValueError(
                    f"Pypi step '{step_name}' missing package_name, "
                    f"package_version, or entry_point."
                )
            # The single techneos/tool-runtime image runs pypi tools. Its
            # ENTRYPOINT pip-installs the tool from the TECHNEOS_INSTALL_* env below,
            # then runs the generic runner with ENTRYPOINT_SPEC. No command
            # override — driving the install via env works identically on the
            # Docker and AWS Batch backends (Batch can't override an entrypoint).
            # Pin the runtime to the version the orchestrator resolved from the
            # compute-artifact inventory (step["image_tag"]); fall back to the
            # deploy env only if it wasn't provided. Never a bare mutable tag.
            image = os.getenv("TECHNEOS_RUNTIME_IMAGE", "techneos/tool-runtime")
            image_tag = step.get("image_tag") or os.getenv("TECHNEOS_RUNTIME_IMAGE_TAG", "latest")

            from operators.codeartifact import mint_codeartifact_token_for_url

            # Mint a fresh CodeArtifact token into the index URL (no-op for devpi).
            index_url = (
                mint_codeartifact_token_for_url(package_index_url)
                if package_index_url
                else ""
            )
            # If the URL is a CodeArtifact endpoint, the token MUST have been
            # injected — a bare URL causes pip to prompt for credentials
            # (EOFError in containers).  Non-CodeArtifact URLs pass through as-is.
            if (
                package_index_url
                and index_url
                and ".d.codeartifact." in package_index_url
                and index_url == package_index_url
            ):
                raise RuntimeError(
                    f"Cannot mint CodeArtifact token for {package_index_url} — "
                    "check CODEARTIFACT_DOMAIN_OWNER / AWS_ACCOUNT_ID env vars "
                    "and the instance IAM role (codeartifact:GetAuthorizationToken)"
                )
            env["TECHNEOS_INSTALL_PACKAGE"] = f"{package_name}=={package_version}"
            env["ENTRYPOINT_SPEC"] = str(entry_point)
            if index_url:
                env["TECHNEOS_INSTALL_INDEX_URL"] = index_url
                host = urlparse(index_url).hostname
                if host:
                    env["TECHNEOS_INSTALL_TRUSTED_HOST"] = host
            command = None  # image entrypoint installs the tool, then runs it
        else:
            raise ValueError(
                f"Unsupported tool_type {tool_type!r}. "
                f"Only 'container' and 'pypi' run as containers (human tools take "
                f"the no-container path)."
            )

        return JobSpec(
            job_name=f"{run_id[:8]}-{step_name}",
            run_id=run_id,
            step_name=step_name,
            image=image,
            tag=image_tag,
            command=command,
            environment=env,
            cpu=str(resources.get("cpu", "1")),
            memory=resources.get("memory", "2Gi"),
            gpu=int(resources.get("gpu", 0)),
            extra=resources.get("extra", {}),
            work_dir_host=_to_host_path(work_dir_host),
            work_dir_local=work_dir_host,
        )

    async def _build_human_spec(
        self,
        *,
        step: dict[str, Any],
        step_name: str,
        run_id: str,
        resources: dict[str, Any],
        callback_url: str,
        callback_token: str,
    ) -> JobSpec:
        """Build a JobSpec for human-type tools.

        No container, no work directory, no inputs download. The
        HumanBackend reads ``human_config`` from ``extra`` and creates a
        TaskRun via task-service. We no longer materialise a parallel
        ToolRun for human steps; task-service owns the run record.
        """
        human_config = step.get("human_config", {})
        input_snapshot = {
            "parameters": step.get("parameters", {}),
            "inputs": step.get("inputs", {}),
        }

        # Prefer the new split assignee fields, falling back to the
        # legacy default_assignee + assignment_type tuple for tool
        # versions registered before the split.
        # Use default_user_email if present, otherwise check assigned_user_id
        # for backward compatibility with older pipeline configs.
        assignment_type = human_config.get("assignment_type", "team")
        assigned_user_email = human_config.get("default_user_email")
        if not assigned_user_email:
            assigned_user_email = human_config.get("assigned_user_email")
        assigned_team_slug = human_config.get("default_team_slug")
        if not assigned_user_email and not assigned_team_slug:
            legacy = human_config.get("default_assignee")
            if legacy:
                if assignment_type == "user":
                    assigned_user_email = legacy
                else:
                    assigned_team_slug = legacy

        return JobSpec(
            job_name=f"{run_id[:8]}-{step_name}",
            run_id=run_id,
            step_name=step_name,
            image="",  # no container
            tag="",
            command=None,
            environment={},
            cpu="0",
            memory="0",
            gpu=0,
            extra={
                "callback_url": callback_url,
                "callback_token": callback_token,
                "org_id": resources.get("org_id", ""),
                "tool_slug": step.get("tool_slug", ""),
                "tool_version_id": step.get("tool_version_id", ""),
                # The orchestrator's run_id IS the pipeline_run_id. task-service
                # will resolve pipeline_step_run_id from (pipeline_run_id,
                # step_name) when not supplied.
                "pipeline_run_id": run_id,
                "step_name": step_name,
                "title": human_config.get("title", f"Task: {step.get('name', step_name)}"),
                "instructions": human_config.get("instructions"),
                "input_snapshot": input_snapshot,
                "assigned_user_email": assigned_user_email,
                "assigned_team_slug": assigned_team_slug,
                "project_lead_id": human_config.get("project_lead_id"),
                "due_in_hours": human_config.get("due_in_hours", 72),
                "priority": human_config.get("priority", "medium"),
                "created_by": step.get("submitted_by") or resources.get("submitted_by"),
            },
        )

    # ── Dataset / upstream resolvers ────────────────────────────────

    async def _resolve_datasets_into_workdir(
        self,
        parameters: dict[str, Any],
        work_dir: Path,
        callback_url: str,
        callback_token: str,
        input_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """Download dataset/upload/paste references into {work_dir}/input/.

        Three kinds of values are recognised:

        1. **Typed pointer dicts** — ``{"type": "paste"|"upload"|"dataset", ...}``.
           Written by the tool-service when binding inputs or canonicalising
           dataset slug references. This is the canonical shape produced
           since the unified-input-modes change.

        2. **Legacy ``dataset``/``*_dataset_id`` string keys** — kept so
           pre-existing pipelines and any in-flight tool runs from before
           the rewrite still resolve.

        3. **String tokens matching ``upload:<id>`` or ``<slug>:v<N>``** —
           also legacy; treated the same as case 2.

        For every matched parameter we emit:

        - ``inputs[{key}_file] = "/work/input/{key}/<file_name>"`` — the
          path the runtime parser reads.
        - ``inputs[{key}_source] = {"type": ..., "content_type": ...,
          "input_kind": ...}`` — sidecar the runtime uses to pick a parser
          without re-deriving from the filename.
        """
        from storage import download_file

        # (param_key, source_type, ref_payload, inputs_key, rel_dir)
        # ref_payload is the dict for typed pointers or the string for legacy.
        to_resolve: list[tuple[str, str, Any, str, str]] = []

        # ── Pass 1: typed-pointer dicts ─────────────────────────────────
        for key, value in parameters.items():
            if isinstance(value, dict) and value.get("type") in ("paste", "upload", "dataset"):
                to_resolve.append((key, value["type"], value, f"{key}_file", key))

        # ── Pass 2: legacy string conventions ──────────────────────────
        for key, value in parameters.items():
            if any(t[0] == key for t in to_resolve):
                continue
            if not (value and isinstance(value, str)):
                continue
            if key in ("dataset_id", "dataset"):
                kind = "upload" if value.startswith("upload:") else "dataset"
                to_resolve.append((key, kind, value, "dataset_file", ""))
            elif key.endswith(("_dataset_id", "_dataset")):
                rel = key.removesuffix("_dataset_id").removesuffix("_dataset")
                kind = "upload" if value.startswith("upload:") else "dataset"
                to_resolve.append((key, kind, value, f"{rel}_dataset_file", rel))

        # Plan B: input_schema-declared keys whose value looks like a ref string.
        for key in input_keys or []:
            if any(t[0] == key for t in to_resolve):
                continue
            value = parameters.get(key)
            if isinstance(value, str) and _looks_like_storage_ref(value):
                kind = "upload" if value.startswith("upload:") else "dataset"
                to_resolve.append((key, kind, value, f"{key}_file", key))

        # Plan C: any remaining string param that looks like a ref.
        for key, value in parameters.items():
            if any(t[0] == key for t in to_resolve):
                continue
            if isinstance(value, str) and _looks_like_storage_ref(value):
                kind = "upload" if value.startswith("upload:") else "dataset"
                to_resolve.append((key, kind, value, f"{key}_file", key))

        resolved: dict[str, Any] = {}
        if not to_resolve:
            return resolved

        for param_key, source_type, payload, inputs_key, rel_dir in to_resolve:
            try:
                info = await _fetch_storage_info(
                    callback_url,
                    callback_token,
                    source_type,
                    payload,
                )
                if not info:
                    logger.warning("Could not resolve %s (%s)", param_key, source_type)
                    continue

                local_dir = work_dir / "input" / rel_dir if rel_dir else work_dir / "input"
                local_dir.mkdir(parents=True, exist_ok=True)
                local_path = local_dir / info["file_name"]
                download_file(
                    storage_key=info["storage_key"],
                    dest_path=str(local_path),
                    bucket=info.get("storage_bucket"),
                )

                # The tool sees container paths, not host paths.
                container_rel = local_path.relative_to(work_dir).as_posix()
                resolved[inputs_key] = f"/work/{container_rel}"

                # Sidecar metadata so the runtime knows how to parse.
                content_type = info.get("content_type")
                if isinstance(payload, dict):
                    content_type = payload.get("content_type") or content_type
                source_field = inputs_key.removesuffix("_file")
                resolved[f"{source_field}_source"] = {
                    "type": source_type,
                    "content_type": content_type,
                }

                logger.info(
                    "Resolved %s (%s) -> /work/%s",
                    param_key,
                    source_type,
                    container_rel,
                )
            except Exception:
                logger.exception("Failed to resolve %s (%s)", param_key, source_type)

        return resolved

    @staticmethod
    def _resolve_upstream_into_workdir(
        step: dict[str, Any],
        work_dir: Path,
    ) -> dict[str, list[str]]:
        """Download upstream artifacts into {work_dir}/input/upstream/{step}/.

        Returns ``{step_name: [container_path, ...]}`` for inputs.json.
        Container paths use the /work prefix the tool will actually see.
        """
        from storage import download_file

        upstream_outputs = step.get("_upstream_outputs", [])
        if not upstream_outputs:
            return {}

        by_step: dict[str, list[str]] = {}
        for artifact in upstream_outputs:
            try:
                file_name = artifact["file_name"]
                # If the artifact carries a source step, namespace by it; else lump under "_".
                src_step = artifact.get("step_name") or "_"
                local_dir = work_dir / "input" / "upstream" / src_step
                local_dir.mkdir(parents=True, exist_ok=True)
                local_path = local_dir / file_name
                download_file(
                    storage_key=artifact["storage_key"],
                    dest_path=str(local_path),
                    bucket=artifact.get("storage_bucket"),
                )
                container_path = f"/work/input/upstream/{src_step}/{file_name}"
                by_step.setdefault(src_step, []).append(container_path)
                logger.info("Downloaded upstream %s -> %s", artifact["storage_key"], container_path)
            except Exception:
                logger.exception("Failed to download upstream %s", artifact.get("file_name"))

        return by_step

    @staticmethod
    def _resolve_declared_inputs(step: dict[str, Any], work_dir: Path) -> dict[str, Any]:
        """Resolve declared upstream input mappings into named input values.

        ``step["inputs"]`` maps a tool input field to an upstream step's
        output — the general mechanism for passing data between steps::

            "inputs": {
              "compounds": {
                "from_step": "screen_alerts",
                "file": "result.json",       # optional, default result.json
                "path": "results",           # optional dotted path to a list
                "filter": {"passed": true}   # optional equality filter on rows
              }
            }

        We locate the matching artifact in ``step["_upstream_outputs"]``
        (tagged with ``step_name`` by the DAG), download + parse it, navigate
        ``path`` to a list, apply ``filter``, and return ``{field: list}`` for
        inputs.json. The tool then reads ``inputs[field]`` directly — no
        ``_file`` parsing needed, so any upstream JSON shape works.
        """
        from storage import download_file

        declared = step.get("inputs") or {}
        upstream = step.get("_upstream_outputs") or []
        resolved: dict[str, Any] = {}

        for field, mapping in declared.items():
            if not isinstance(mapping, dict) or not mapping.get("from_step"):
                continue
            from_step = mapping["from_step"]
            want_file = mapping.get("file", "result.json")

            art = next(
                (
                    a
                    for a in upstream
                    if a.get("step_name") == from_step and a.get("file_name") == want_file
                ),
                None,
            ) or next((a for a in upstream if a.get("step_name") == from_step), None)
            if art is None:
                logger.warning(
                    "Declared input %r: no upstream artifact from step %r", field, from_step
                )
                continue

            try:
                dest = work_dir / "input" / f"_upstream_{field}_{want_file}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                download_file(
                    storage_key=art["storage_key"],
                    dest_path=str(dest),
                    bucket=art.get("storage_bucket"),
                )
                doc: Any = json.loads(dest.read_text())
            except Exception:
                logger.exception("Declared input %r: failed to download/parse upstream", field)
                continue

            node: Any = doc
            path = mapping.get("path")
            if path:
                for part in str(path).split("."):
                    node = node.get(part) if isinstance(node, dict) else None
                    if node is None:
                        break
            if not isinstance(node, list):
                logger.warning(
                    "Declared input %r: path %r did not resolve to a list (got %s)",
                    field,
                    path,
                    type(node).__name__,
                )
                continue

            flt = mapping.get("filter") or {}
            if isinstance(flt, dict) and flt:
                node = [
                    e
                    for e in node
                    if isinstance(e, dict) and all(e.get(k) == v for k, v in flt.items())
                ]

            resolved[field] = node
            logger.info("Declared input %r ← step %r (%d row(s))", field, from_step, len(node))

        return resolved

    # ── Artifact helpers ────────────────────────────────────────────

    @staticmethod
    async def _upload_and_register_artifacts(
        run_id: str,
        step_name: str,
        files: dict[str, bytes],
        callback_url: str,
        callback_token: str,
        resource_path: str = "pipeline-runs",
        key_prefix: str | None = None,
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Upload output files to MinIO and register them via the platform API.

        ``key_prefix`` is the orchestrator-supplied object-store prefix —
        e.g. ``pipeline-runs/{slug}/v{N}/{run_id}/{step_name}`` or
        ``tool-runs/{slug}/v{N}/{run_id}``. When omitted the worker falls
        back to ``{resource_path}/{run_id}/{step_name}`` so in-flight DAG
        runs from before this change still work.

        Returns a tuple of (artifact_ids, artifact_keys) where
        artifact_keys is a list of ``{"storage_key": ..., "file_name": ...}``
        dicts for step-to-step data passing.
        """
        from storage import upload_artifact

        artifact_ids: list[str] = []
        artifact_keys: list[dict[str, str]] = []

        for file_name, data in files.items():
            # Upload to MinIO
            meta = upload_artifact(
                run_id=run_id,
                step_name=step_name,
                file_name=file_name,
                data=data,
                resource_path=resource_path,
                key_prefix=key_prefix,
            )

            artifact_keys.append(
                {
                    "storage_key": meta["storage_key"],
                    "storage_bucket": meta["storage_bucket"],
                    "file_name": meta["file_name"],
                }
            )

            # Infer artifact type from extension
            artifact_type = _infer_artifact_type(file_name)

            # Register via platform API
            if callback_url:
                aid = await _register_artifact(
                    callback_url=callback_url,
                    callback_token=callback_token,
                    run_id=run_id,
                    step_name=step_name,
                    file_name=file_name,
                    artifact_type=artifact_type,
                    resource_path=resource_path,
                    file_size=meta["file_size"],
                    content_type=meta["content_type"],
                    checksum_sha256=meta["checksum_sha256"],
                    storage_bucket=meta["storage_bucket"],
                    storage_key=meta["storage_key"],
                )
                if aid:
                    artifact_ids.append(aid)

        return artifact_ids, artifact_keys

    # ── Cancel check ───────────────────────────────────────────────

    @staticmethod
    async def _is_run_cancelled(
        callback_url: str,
        token: str,
        run_id: str,
        resource_path: str = "pipeline-runs",
    ) -> bool:
        """Check if the platform has marked this run as cancelled."""
        if not callback_url:
            return False
        resource = resource_path or "pipeline-runs"
        url = f"{callback_url}/api/v1/{resource}/{run_id}"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    url,
                    headers={"X-Internal-Token": token} if token else {},
                )
                if resp.is_success:
                    return resp.json().get("status") == "cancelled"
        except httpx.HTTPError:
            pass
        return False

    # ── Status reporting ────────────────────────────────────────────

    @staticmethod
    async def _report_step_status(
        callback_url: str,
        token: str,
        run_id: str,
        step_name: str,
        status: str,
        error_message: str | None = None,
        outputs: dict[str, Any] | None = None,
        resource_path: str = "pipeline-runs",
    ) -> None:
        """PATCH step status back to the platform API."""
        if not callback_url:
            logger.debug("No callback URL — skipping status report")
            return

        resource = resource_path or "pipeline-runs"
        url = f"{callback_url}/api/v1/{resource}/{run_id}/steps/{step_name}/status"
        payload: dict[str, Any] = {"status": status}
        if error_message:
            payload["error_message"] = error_message
        if outputs:
            payload["outputs"] = outputs

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.patch(
                    url,
                    json=payload,
                    headers={"X-Internal-Token": token} if token else {},
                )
                if not resp.is_success:
                    logger.warning(
                        "Callback failed for step %s: %s %s",
                        step_name,
                        resp.status_code,
                        resp.text[:200],
                    )
        except httpx.HTTPError as exc:
            logger.warning("Callback error for step %s: %s", step_name, exc)


# ── Module-level helpers ────────────────────────────────────────────


def _make_shared_tmpdir(prefix: str = "techneos-") -> str:
    """Create a temp directory in the shared input area.

    Returns the *scheduler-local* path.  Use ``_to_host_path`` to get
    the host-side equivalent for Docker bind-mounts.
    """
    if _SHARED_INPUT_DIR:
        base = Path(_SHARED_INPUT_DIR)
        base.mkdir(parents=True, exist_ok=True)
        return tempfile.mkdtemp(prefix=prefix, dir=str(base))
    return tempfile.mkdtemp(prefix=prefix)


def _to_host_path(local_path: str) -> str:
    """Translate a scheduler-container path to its host equivalent.

    If the shared input directory is configured, replaces the
    scheduler-side prefix with the host-side prefix so Docker can
    bind-mount the file into sibling containers.
    """
    if _SHARED_INPUT_DIR and _HOST_SHARED_INPUT_DIR and local_path.startswith(_SHARED_INPUT_DIR):
        return local_path.replace(_SHARED_INPUT_DIR, _HOST_SHARED_INPUT_DIR, 1)
    return local_path


def _to_local_path(host_path: str) -> str:
    """Translate a host path back to its scheduler-container equivalent.

    Inverse of ``_to_host_path``.  Used by InlineBackend which runs
    inside the scheduler container and needs local filesystem paths.
    """
    if (
        _HOST_SHARED_INPUT_DIR
        and _SHARED_INPUT_DIR
        and host_path.startswith(_HOST_SHARED_INPUT_DIR)
    ):
        return host_path.replace(_HOST_SHARED_INPUT_DIR, _SHARED_INPUT_DIR, 1)
    return host_path


def _cleanup_work_dir(work_dir_host: str) -> None:
    """Remove the per-step work dir created for a container tool step.

    work_dir_host may be a host-side path (TECHNEOS_HOST_SHARED_INPUT_DIR
    rewritten) — translate back to the scheduler-local path before unlink.
    """
    import shutil

    local = work_dir_host
    if _HOST_SHARED_INPUT_DIR and _SHARED_INPUT_DIR and local.startswith(_HOST_SHARED_INPUT_DIR):
        local = local.replace(_HOST_SHARED_INPUT_DIR, _SHARED_INPUT_DIR, 1)
    if local.startswith(tempfile.gettempdir()) or (
        _SHARED_INPUT_DIR and local.startswith(_SHARED_INPUT_DIR)
    ):
        try:
            shutil.rmtree(local)
            logger.debug("Cleaned up work dir %s", local)
        except Exception:
            logger.debug("Failed to clean up work dir %s", local)


async def _fetch_storage_info(
    callback_url: str,
    callback_token: str,
    source_type: str,
    payload: Any,
) -> dict[str, Any] | None:
    """Resolve a typed pointer or legacy ref string to storage info.

    Routes to the right backend lookup based on ``source_type``:

    - ``"paste"`` and ``"upload"`` both hit ``/tool-runs/inputs/{id}`` —
      paste-mode inputs are stored as ToolRunInput rows so the worker
      treats them identically. ``content_type`` from the API response is
      propagated so the runtime parser can pick a format.
    - ``"dataset"`` hits ``/datasets/resolve-storage`` via the existing
      helper.

    ``payload`` is either a dict (typed pointer) or a legacy string token.
    """
    if source_type in ("paste", "upload"):
        if isinstance(payload, dict):
            # After submit_run relocates files from scratch to canonical
            # storage, the typed pointer carries the canonical storage_key
            # and storage_bucket inline — use those directly instead of
            # calling back to an API that has no corresponding row.
            if payload.get("storage_key") and payload.get("storage_bucket"):
                return {
                    "storage_bucket": payload["storage_bucket"],
                    "storage_key": payload["storage_key"],
                    "file_name": payload.get("file_name"),
                    "content_type": payload.get("content_type"),
                    "source": source_type,
                }
            input_id = payload.get("input_id")
        elif isinstance(payload, str) and payload.startswith("upload:"):
            input_id = payload.removeprefix("upload:")
        else:
            return None
        if not input_id:
            return None
        return await _fetch_upload_storage(callback_url, callback_token, input_id)

    if source_type == "dataset":
        ref = payload.get("ref") if isinstance(payload, dict) else payload
        if not isinstance(ref, str) or not ref:
            return None
        return await _fetch_dataset_storage(callback_url, callback_token, ref)

    logger.warning("Unknown source_type %r — skipping resolve", source_type)
    return None


async def _fetch_dataset_storage(
    callback_url: str,
    callback_token: str,
    dataset_ref: str,
) -> dict[str, Any] | None:
    """Call the platform API to resolve a dataset reference to its storage location.

    The *dataset_ref* can be any of:
    - ``my-dataset:v2`` — specific version by slug
    - ``my-dataset`` — latest ready version by slug
    - ``<uuid>:v3`` — specific version by UUID
    - ``<uuid>`` — latest ready version by UUID

    Returns ``{"storage_bucket", "storage_key", "file_name", "version", "dataset_id"}``
    or *None* on failure.
    """
    if not callback_url:
        logger.warning("No callback_url — cannot resolve dataset %s", dataset_ref)
        return None

    url = f"{callback_url}/api/v1/datasets/resolve-storage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                url,
                params={"ref": dataset_ref},
                headers={"X-Internal-Token": callback_token} if callback_token else {},
            )
            if resp.is_success:
                return resp.json()
            logger.warning(
                "Dataset storage lookup failed for %s: %s %s",
                dataset_ref,
                resp.status_code,
                resp.text[:200],
            )
    except httpx.HTTPError as exc:
        logger.warning("Dataset storage lookup error for %s: %s", dataset_ref, exc)
    return None


_DATASET_REF_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*:v\d+$")


def _looks_like_storage_ref(value: str) -> bool:
    """Heuristic: does this string look like a dataset/upload reference?

    Strict patterns only — bare slugs are not recognised, so values
    that happen to look like identifiers don't get accidentally resolved.

    - ``upload:<input_id>`` — a staged ToolRunInput.
    - ``<slug>:v<N>`` — a specific dataset version.

    Bare slugs / UUIDs are intentionally NOT matched: tool authors who
    want "latest" should provide ``slug:vN`` explicitly. For input_keys
    that aren't refs, the value passes through to params.json as inline
    data.
    """
    if not isinstance(value, str):
        return False
    if value.startswith("upload:"):
        return True
    return bool(_DATASET_REF_RE.match(value))


async def _fetch_upload_storage(
    callback_url: str,
    callback_token: str,
    input_id: str,
) -> dict[str, Any] | None:
    """Resolve a tool-run upload reference (``upload:<id>``) to storage info.

    Returns ``{"storage_bucket", "storage_key", "file_name"}`` or *None*
    on failure. Used when a tool parameter value starts with ``upload:``.
    """
    if not callback_url:
        logger.warning("No callback_url — cannot resolve upload %s", input_id)
        return None

    url = f"{callback_url}/api/v1/tool-runs/inputs/{input_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                url,
                headers={"X-Internal-Token": callback_token} if callback_token else {},
            )
            if resp.is_success:
                data = resp.json()
                return {
                    "storage_bucket": data.get("storage_bucket"),
                    "storage_key": data.get("storage_key"),
                    "file_name": data.get("file_name"),
                    "content_type": data.get("content_type"),
                    "source": data.get("source"),
                }
            logger.warning(
                "Upload storage lookup failed for %s: %s %s",
                input_id,
                resp.status_code,
                resp.text[:200],
            )
    except httpx.HTTPError as exc:
        logger.warning("Upload storage lookup error for %s: %s", input_id, exc)
    return None


def _infer_artifact_type(file_name: str) -> str:
    """Guess the artifact type from file extension."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    type_map = {
        "pdf": "report",
        "html": "report",
        "csv": "table",
        "tsv": "table",
        "xlsx": "table",
        "png": "plot",
        "jpg": "plot",
        "jpeg": "plot",
        "svg": "plot",
        "sdf": "file",
        "pdb": "file",
        "mol2": "file",
        "pth": "model",
        "onnx": "model",
        "pkl": "model",
        "json": "file",
    }
    return type_map.get(ext, "file")


async def _register_artifact(
    callback_url: str,
    callback_token: str,
    run_id: str,
    step_name: str,
    file_name: str,
    artifact_type: str,
    file_size: int,
    content_type: str,
    checksum_sha256: str,
    storage_bucket: str,
    storage_key: str,
    resource_path: str = "pipeline-runs",
) -> str | None:
    """POST artifact metadata to the platform API. Returns artifact ID or None."""
    resource = resource_path or "pipeline-runs"
    url = f"{callback_url}/api/v1/{resource}/{run_id}/artifacts"
    payload: dict[str, Any] = {
        # The pipeline service's PipelineArtifactCreate requires a human-readable
        # `name` (separate from `file_name`); default it to the file name so
        # registration doesn't 422. The tool service ignores the extra field.
        "name": file_name,
        "artifact_type": artifact_type,
        "file_name": file_name,
        "file_size": file_size,
        "content_type": content_type,
        "checksum_sha256": checksum_sha256,
        "storage_bucket": storage_bucket,
        "storage_key": storage_key,
        "metadata": {"artifact_type": artifact_type},
    }
    # The pipeline service tracks per-step artifacts; the tool service
    # doesn't have a step concept and ignores step_name.
    if resource == "pipeline-runs":
        payload["step_name"] = step_name
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Internal-Token": callback_token} if callback_token else {},
            )
            if resp.is_success:
                data = resp.json()
                logger.info("Registered artifact '%s' (id=%s)", file_name, data.get("id"))
                return data.get("id")
            else:
                logger.warning(
                    "Artifact registration failed for %s: %s %s",
                    file_name,
                    resp.status_code,
                    resp.text[:200],
                )
    except httpx.HTTPError as exc:
        logger.warning("Artifact registration error for %s: %s", file_name, exc)
    return None
