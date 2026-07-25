"""Docker compute backend — runs tool containers locally.

Intended for development and testing.  Uses the Docker SDK (``docker``
package) to pull images and run containers, then collects exit code and
logs.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from backends.base import ComputeBackend, JobResult, JobSpec, JobStatus
from backends.ecr_auth import get_ecr_auth_config

logger = logging.getLogger(__name__)


class DockerBackend(ComputeBackend):
    """Run jobs as local Docker containers."""

    def __init__(self) -> None:
        self._docker: docker.DockerClient | None = None

    @property
    def docker(self) -> docker.DockerClient:
        if self._docker is None:
            self._docker = docker.from_env()
        return self._docker

    async def submit_job(self, spec: JobSpec) -> str:
        """Pull image and start a detached container."""
        image_ref = f"{spec.image}:{spec.tag}"

        def _run() -> str:
            # Image resolution. Tools run pinned, immutable version tags (the
            # orchestrator resolves them from the compute-artifact inventory —
            # never :latest), so a cached copy is always safe to reuse: we hit
            # the registry only when the image isn't cached. This also avoids a
            # doomed pull of a local-only dev image (bare name → Docker Hub 404).
            #
            # For ECR images the host's credential helper does not apply to
            # docker-py talking to the daemon socket, so we mint a token via the
            # worker IAM role and pass it as auth_config. A successful pull
            # caches the image so containers.run() below won't re-pull
            # (unauthenticated) and 500.
            cached = True
            try:
                self.docker.images.get(image_ref)
            except (NotFound, DockerException):
                cached = False

            if cached:
                logger.info("Image %s already cached — skipping pull", image_ref)
            else:
                try:
                    auth_config = get_ecr_auth_config(spec.image)
                    self.docker.images.pull(spec.image, tag=spec.tag, auth_config=auth_config)
                except DockerException:
                    logger.warning("Failed to pull %s — using cached image", image_ref)

            # Build container kwargs
            container_name = f"techneos-{spec.run_id[:8]}-{spec.step_name}"
            kwargs: dict[str, Any] = {
                "image": image_ref,
                "name": container_name,
                "detach": True,
                "environment": spec.environment,
                "labels": {
                    "techneos.run_id": spec.run_id,
                    "techneos.step_name": spec.step_name,
                },
            }

            if spec.command:
                kwargs["command"] = spec.command

            # GPU support
            if spec.gpu > 0:
                kwargs["device_requests"] = [
                    docker.types.DeviceRequest(count=spec.gpu, capabilities=[["gpu"]])
                ]

            # Resource limits
            mem_bytes = _parse_memory(spec.memory)
            if mem_bytes:
                kwargs["mem_limit"] = mem_bytes

            # ── Network ──────────────────────────────────────────────────
            # By default, sibling containers land on the default bridge
            # network, which cannot reach Compose services by hostname.
            # The DOCKER_NETWORK env var (set from DOCKER_NETWORK_NAME in
            # docker-compose.yml) tells us which Compose network to join so
            # tool containers can resolve devpi, minio, etc. by hostname.
            # Fall back to auto-detecting the scheduler's own network if
            # the env var is not set.
            docker_network = os.environ.get("DOCKER_NETWORK", "")
            if not docker_network:
                try:
                    hostname = os.uname().nodename
                    own = self.docker.containers.get(hostname)
                    nets = own.attrs.get("NetworkSettings", {}).get("Networks", {})
                    if nets:
                        docker_network = next(iter(nets))
                except Exception:
                    pass
            if docker_network:
                kwargs["network"] = docker_network

            # ── Bind mounts ─────────────────────────────────────────────
            # Single rw mount of the host work dir at /work. The container reads
            # inputs.json/params.json from there and writes outputs straight to
            # the host (no docker cp).
            volumes: dict[str, dict[str, str]] = {}
            if spec.work_dir_host:
                volumes[spec.work_dir_host] = {"bind": "/work", "mode": "rw"}
                logger.info(
                    "Mounting work dir %s -> /work (rw) for container %s",
                    spec.work_dir_host,
                    container_name,
                )

            if volumes:
                kwargs["volumes"] = volumes

            # Remove stale container from previous attempt (retry support)
            try:
                stale = self.docker.containers.get(container_name)
                logger.info("Removing stale container %s from previous attempt", container_name)
                stale.remove(force=True)
            except NotFound:
                pass

            container = self.docker.containers.run(**kwargs)
            return container.id  # type: ignore[return-value]

        return await asyncio.to_thread(_run)

    async def get_job_status(self, job_id: str) -> JobResult:
        """Inspect a container and return normalised status."""

        def _status() -> JobResult:
            try:
                container = self.docker.containers.get(job_id)
            except NotFound:
                return JobResult(
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    error_message="Container not found",
                )

            state = container.status  # created | running | paused | exited | dead
            attrs = container.attrs or {}
            exit_code = attrs.get("State", {}).get("ExitCode")

            if state == "running":
                return JobResult(job_id=job_id, status=JobStatus.RUNNING)
            if state == "exited":
                status = JobStatus.COMPLETED if exit_code == 0 else JobStatus.FAILED
                error_msg = None
                if exit_code != 0:
                    # Capture container logs so the error is actionable
                    try:
                        tail_logs = (
                            container.logs(tail=50).decode("utf-8", errors="replace").strip()
                        )
                    except Exception:
                        tail_logs = ""
                    error_msg = f"Exit code {exit_code}"
                    if tail_logs:
                        error_msg += f"\n--- container logs (last 50 lines) ---\n{tail_logs}"
                return JobResult(
                    job_id=job_id,
                    status=status,
                    exit_code=exit_code,
                    error_message=error_msg,
                )
            # created / paused / restarting
            return JobResult(job_id=job_id, status=JobStatus.PENDING)

        return await asyncio.to_thread(_status)

    async def cancel_job(self, job_id: str) -> None:
        def _stop() -> None:
            try:
                container = self.docker.containers.get(job_id)
                container.stop(timeout=10)
                container.remove(force=True)
            except NotFound:
                pass

        await asyncio.to_thread(_stop)

    async def get_logs(self, job_id: str, tail: int = 500) -> str:
        def _logs() -> str:
            try:
                container = self.docker.containers.get(job_id)
                return container.logs(tail=tail).decode("utf-8", errors="replace")
            except NotFound:
                return ""

        return await asyncio.to_thread(_logs)

    async def collect_outputs(
        self,
        job_id: str,
        work_dir_host: str | None = None,
    ) -> dict[str, bytes]:
        """Collect output files from a completed job.

        Reads everything under ``{work_dir_host}/output/`` directly from the
        host filesystem — no docker cp, no tar serialisation, the container
        already wrote through the bind mount.

        Returns ``filename → bytes``. Subdirectories under output/ are
        flattened with slashes preserved (e.g. ``plots/mw.png``).
        """
        if not work_dir_host:
            return {}
        return await asyncio.to_thread(self._collect_from_host, work_dir_host)

    @staticmethod
    def _collect_from_host(work_dir_host: str) -> dict[str, bytes]:
        """Read every file under {work_dir_host}/output/ into memory.

        ``work_dir_host`` is the host-side path (e.g.
        ``/Users/.../.dev-tmp/inputs/techneos-work-...``), which is what the
        Docker daemon bind-mounts. However, this code runs inside the
        scheduler container where that host path may not be visible — the
        scheduler sees the *container-local* equivalent (e.g.
        ``/tmp/techneos-shared-inputs/techneos-work-...``). If the host path doesn't
        exist, we translate it back to the scheduler-local path via the
        same shared-input convention used in the operator module.
        """
        from pathlib import Path

        out_dir = Path(work_dir_host) / "output"
        if not out_dir.is_dir():
            # Translate host path → scheduler-local path (reverse of _to_host_path).
            host_prefix = os.environ.get("TECHNEOS_HOST_SHARED_INPUT_DIR", "")
            local_prefix = os.environ.get("TECHNEOS_SHARED_INPUT_DIR", "")
            if host_prefix and local_prefix and work_dir_host.startswith(host_prefix):
                local_path = work_dir_host.replace(host_prefix, local_prefix, 1)
                out_dir = Path(local_path) / "output"
            if not out_dir.is_dir():
                logger.debug("No output dir at %s (tried host and local)", out_dir)
                return {}

        files: dict[str, bytes] = {}
        for p in out_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(out_dir).as_posix()
                files[rel] = p.read_bytes()
        logger.info("Collected %d output file(s) from host work dir %s", len(files), out_dir)
        return files

    async def cleanup_container(self, job_id: str) -> None:
        """Remove a stopped container."""

        def _rm() -> None:
            try:
                container = self.docker.containers.get(job_id)
                container.remove(force=True)
            except NotFound:
                pass

        await asyncio.to_thread(_rm)


def _parse_memory(mem: str) -> int | None:
    """Convert e.g. '4Gi' → bytes.  Returns None on parse failure."""
    mem = mem.strip()
    try:
        if mem.endswith("Gi"):
            return int(float(mem[:-2]) * 1024**3)
        if mem.endswith("Mi"):
            return int(float(mem[:-2]) * 1024**2)
        if mem.endswith("G"):
            return int(float(mem[:-1]) * 1000**3)
        if mem.endswith("M"):
            return int(float(mem[:-1]) * 1000**2)
        return int(mem)
    except (ValueError, TypeError):
        return None
