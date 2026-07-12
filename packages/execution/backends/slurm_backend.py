"""Slurm compute backend — runs tool containers on HPC clusters via SSH.

Submits containerised pipeline steps as Slurm batch jobs by SSHing
into the cluster's submit node.  Containers are executed via
Singularity/Apptainer, the standard container runtime on HPC systems.

Prerequisites
-------------
* SSH access to a Slurm submit/login node (key-based auth).
* Singularity/Apptainer installed on the cluster compute nodes.
* A shared filesystem (NFS/Lustre/GPFS) visible to both the submit
  node and all compute nodes.

Environment variables
---------------------
``SLURM_SUBMIT_HOST``
    SSH hostname of the cluster submit/login node (required).
``SLURM_SSH_USER``
    SSH username (default: current user via ``USER``).
``SLURM_SSH_KEY_PATH``
    Path to the SSH private key (default: ``~/.ssh/id_rsa``).
``SLURM_SSH_PORT``
    SSH port (default: 22).
``SLURM_PARTITION``
    Default Slurm partition/queue (default: ``"default"``).
``SLURM_ACCOUNT``
    Default billing/allocation account (optional).
``SLURM_WORK_DIR``
    Base path on the cluster shared filesystem for work directories
    (default: ``/scratch/techneos``).
``SINGULARITY_CACHE_DIR``
    Path on the cluster where ``.sif`` images are cached
    (default: ``/scratch/techneos/singularity-cache``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
from pathlib import Path, PurePosixPath

from backends.base import ComputeBackend, JobResult, JobSpec, JobStatus

logger = logging.getLogger(__name__)

_SLURM_STATUS_MAP: dict[str, JobStatus] = {
    "PENDING": JobStatus.PENDING,
    "CONFIGURING": JobStatus.PENDING,
    "RUNNING": JobStatus.RUNNING,
    "COMPLETING": JobStatus.RUNNING,
    "COMPLETED": JobStatus.COMPLETED,
    "FAILED": JobStatus.FAILED,
    "CANCELLED": JobStatus.CANCELLED,
    "CANCELLED+": JobStatus.CANCELLED,
    "TIMEOUT": JobStatus.FAILED,
    "NODE_FAIL": JobStatus.FAILED,
    "PREEMPTED": JobStatus.FAILED,
    "OUT_OF_MEMORY": JobStatus.FAILED,
}


class SlurmBackend(ComputeBackend):
    """Execute jobs on a Slurm HPC cluster via SSH."""

    def __init__(
        self,
        submit_host: str | None = None,
        ssh_user: str | None = None,
        ssh_key_path: str | None = None,
        ssh_port: int | None = None,
        partition: str | None = None,
        account: str | None = None,
        work_dir: str | None = None,
        singularity_cache: str | None = None,
    ) -> None:
        self._submit_host = submit_host or os.getenv("SLURM_SUBMIT_HOST", "")
        if not self._submit_host:
            raise ValueError(
                "SLURM_SUBMIT_HOST must be set (SSH hostname of the cluster submit node)"
            )
        self._ssh_user = ssh_user or os.getenv("SLURM_SSH_USER", os.getenv("USER", ""))
        self._ssh_key_path = ssh_key_path or os.getenv(
            "SLURM_SSH_KEY_PATH", os.path.expanduser("~/.ssh/id_rsa")
        )
        self._ssh_port = ssh_port or int(os.getenv("SLURM_SSH_PORT", "22"))
        self._partition = partition or os.getenv("SLURM_PARTITION", "default")
        self._account = account or os.getenv("SLURM_ACCOUNT", "")
        self._work_dir = work_dir or os.getenv("SLURM_WORK_DIR", "/scratch/techneos")
        self._singularity_cache = singularity_cache or os.getenv(
            "SINGULARITY_CACHE_DIR", "/scratch/techneos/singularity-cache"
        )
        # Track remote work dirs for cleanup
        self._job_work_dirs: dict[str, str] = {}

    # ── SSH helpers ──────────────────────────────────────────────────

    def _ssh_base_args(self) -> list[str]:
        return [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=30",
            "-i", self._ssh_key_path,
            "-p", str(self._ssh_port),
            f"{self._ssh_user}@{self._submit_host}",
        ]

    async def _ssh_run(self, remote_cmd: str) -> tuple[int, str, str]:
        """Run a command on the submit node via SSH.

        Returns (returncode, stdout, stderr).
        """
        args = [*self._ssh_base_args(), remote_cmd]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        return proc.returncode or 0, stdout, stderr

    async def _rsync_to_cluster(self, local_path: str, remote_path: str) -> None:
        """Copy a directory from the Airflow host to the cluster."""
        remote_dest = f"{self._ssh_user}@{self._submit_host}:{remote_path}"
        args = [
            "rsync", "-az", "--mkpath",
            "-e", f"ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -i {self._ssh_key_path} -p {self._ssh_port}",
            f"{local_path}/",
            f"{remote_dest}/",
        ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            raise RuntimeError(f"rsync to cluster failed: {stderr}")
        logger.info("Synced %s → %s:%s", local_path, self._submit_host, remote_path)

    async def _rsync_from_cluster(self, remote_path: str, local_path: str) -> None:
        """Copy a directory from the cluster back to the Airflow host."""
        remote_src = f"{self._ssh_user}@{self._submit_host}:{remote_path}"
        os.makedirs(local_path, exist_ok=True)
        args = [
            "rsync", "-az",
            "-e", f"ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -i {self._ssh_key_path} -p {self._ssh_port}",
            f"{remote_src}/",
            f"{local_path}/",
        ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            raise RuntimeError(f"rsync from cluster failed: {stderr}")
        logger.info("Synced %s:%s → %s", self._submit_host, remote_path, local_path)

    # ── Singularity image management ─────────────────────────────────

    def _sif_path(self, image: str, tag: str) -> str:
        """Derive the .sif file path on the cluster for a Docker image ref."""
        safe_name = re.sub(r"[/:@]", "_", image)
        return f"{self._singularity_cache}/{safe_name}_{tag}.sif"

    async def _ensure_sif_image(self, image: str, tag: str) -> str:
        """Pull a Docker image into a Singularity .sif file if not cached."""
        sif = self._sif_path(image, tag)
        rc, stdout, _ = await self._ssh_run(f"test -f {shlex.quote(sif)} && echo exists")
        if stdout.strip() == "exists" and tag != "latest":
            logger.info("Singularity image cached: %s", sif)
            return sif

        docker_uri = f"docker://{image}:{tag}"
        logger.info("Pulling Singularity image %s → %s", docker_uri, sif)
        pull_cmd = (
            f"mkdir -p {shlex.quote(self._singularity_cache)} && "
            f"singularity pull --force {shlex.quote(sif)} {shlex.quote(docker_uri)}"
        )
        rc, stdout, stderr = await self._ssh_run(pull_cmd)
        if rc != 0:
            raise RuntimeError(
                f"Failed to pull Singularity image {docker_uri}: {stderr or stdout}"
            )
        return sif

    # ── ComputeBackend interface ─────────────────────────────────────

    async def submit_job(self, spec: JobSpec) -> str:
        """Stage files, write a batch script, and submit via sbatch."""
        remote_work_dir = str(
            PurePosixPath(self._work_dir) / "runs" / spec.run_id[:12] / spec.step_name
        )

        # Create remote work dir
        await self._ssh_run(f"mkdir -p {shlex.quote(remote_work_dir)}")

        # Stage input files to cluster
        if spec.work_dir_host:
            await self._rsync_to_cluster(spec.work_dir_host, remote_work_dir)

        # Ensure the Singularity image is available
        sif = await self._ensure_sif_image(spec.image, spec.tag)

        # Build environment export lines
        env_exports = "\n".join(
            f"export {k}={shlex.quote(v)}" for k, v in spec.environment.items()
        )

        # Build sbatch directives
        partition = spec.extra.get("partition", self._partition)
        account = spec.extra.get("account", self._account)
        time_limit = spec.extra.get("time_limit", "24:00:00")
        memory_mb = _memory_to_mb(spec.memory)

        directives = [
            f"#SBATCH --job-name=techneos-{spec.run_id[:8]}-{spec.step_name}",
            f"#SBATCH --partition={partition}",
            f"#SBATCH --cpus-per-task={spec.cpu}",
            f"#SBATCH --mem={memory_mb}M",
            f"#SBATCH --time={time_limit}",
            f"#SBATCH --output={remote_work_dir}/slurm-%j.out",
            f"#SBATCH --error={remote_work_dir}/slurm-%j.err",
        ]
        if account:
            directives.append(f"#SBATCH --account={account}")
        if spec.gpu > 0:
            directives.append(f"#SBATCH --gres=gpu:{spec.gpu}")

        directives_block = "\n".join(directives)

        # Command to run inside the container
        cmd = " ".join(shlex.quote(c) for c in spec.command) if spec.command else ""

        batch_script = f"""#!/bin/bash
{directives_block}

# Environment variables
{env_exports}
export TECHNEOS_WORK_DIR=/work

# Run via Singularity
singularity exec --cleanenv --bind {remote_work_dir}:/work {shlex.quote(sif)} {cmd}
"""

        script_path = f"{remote_work_dir}/job.sh"
        write_cmd = f"cat > {shlex.quote(script_path)} << 'SLURM_EOF'\n{batch_script}SLURM_EOF"
        rc, _, stderr = await self._ssh_run(write_cmd)
        if rc != 0:
            raise RuntimeError(f"Failed to write batch script: {stderr}")

        # Submit
        rc, stdout, stderr = await self._ssh_run(
            f"sbatch --parsable {shlex.quote(script_path)}"
        )
        if rc != 0:
            raise RuntimeError(f"sbatch failed: {stderr or stdout}")

        job_id = stdout.strip().split(";")[0]  # parsable format: jobid[;cluster]
        if not job_id.isdigit():
            raise RuntimeError(f"Unexpected sbatch output: {stdout}")

        self._job_work_dirs[job_id] = remote_work_dir
        logger.info(
            "Submitted Slurm job %s (partition=%s) for step '%s'",
            job_id, partition, spec.step_name,
        )
        return job_id

    async def get_job_status(self, job_id: str) -> JobResult:
        """Query job status via sacct."""
        rc, stdout, _ = await self._ssh_run(
            f"sacct -j {job_id} --format=State,ExitCode --noheader --parsable2 2>/dev/null"
        )
        if rc != 0 or not stdout.strip():
            # sacct may not have the job yet if it was just submitted; try squeue
            rc2, stdout2, _ = await self._ssh_run(
                f"squeue -j {job_id} --noheader --format=%T 2>/dev/null"
            )
            if rc2 == 0 and stdout2.strip():
                slurm_state = stdout2.strip().split("\n")[0].strip()
                status = _SLURM_STATUS_MAP.get(slurm_state, JobStatus.PENDING)
                return JobResult(job_id=job_id, status=status)
            return JobResult(job_id=job_id, status=JobStatus.PENDING)

        # sacct can return multiple lines (job + job steps); use the first (main job)
        first_line = stdout.strip().split("\n")[0]
        parts = first_line.split("|")
        slurm_state = parts[0].strip().rstrip("+")
        exit_code_str = parts[1].strip() if len(parts) > 1 else "0:0"

        status = _SLURM_STATUS_MAP.get(slurm_state, JobStatus.PENDING)

        exit_code = None
        error_msg = None
        if ":" in exit_code_str:
            code, _ = exit_code_str.split(":", 1)
            exit_code = int(code) if code.isdigit() else None
        elif exit_code_str.isdigit():
            exit_code = int(exit_code_str)

        if status == JobStatus.FAILED:
            error_msg = f"Slurm state: {slurm_state}"
            if exit_code is not None and exit_code != 0:
                error_msg += f", exit code {exit_code}"

        return JobResult(
            job_id=job_id,
            status=status,
            exit_code=exit_code,
            error_message=error_msg,
        )

    async def cancel_job(self, job_id: str) -> None:
        rc, _, stderr = await self._ssh_run(f"scancel {job_id}")
        if rc != 0:
            logger.warning("scancel %s failed: %s", job_id, stderr)
        else:
            logger.info("Cancelled Slurm job %s", job_id)

    async def get_logs(self, job_id: str, tail: int = 500) -> str:
        remote_work_dir = self._job_work_dirs.get(job_id, "")
        if not remote_work_dir:
            return ""

        stdout_file = f"{remote_work_dir}/slurm-{job_id}.out"
        stderr_file = f"{remote_work_dir}/slurm-{job_id}.err"

        _, stdout_log, _ = await self._ssh_run(
            f"tail -n {tail} {shlex.quote(stdout_file)} 2>/dev/null"
        )
        _, stderr_log, _ = await self._ssh_run(
            f"tail -n {tail} {shlex.quote(stderr_file)} 2>/dev/null"
        )
        parts = []
        if stdout_log:
            parts.append(stdout_log)
        if stderr_log:
            parts.append(f"--- stderr ---\n{stderr_log}")
        return "\n".join(parts)

    async def collect_outputs(
        self,
        job_id: str,
        work_dir_host: str | None = None,
    ) -> dict[str, bytes]:
        """Rsync outputs from the cluster back to the local host."""
        remote_work_dir = self._job_work_dirs.get(job_id, "")
        if not remote_work_dir or not work_dir_host:
            return {}

        remote_output = f"{remote_work_dir}/output"
        local_output = str(Path(work_dir_host) / "output")

        try:
            await self._rsync_from_cluster(remote_output, local_output)
        except RuntimeError:
            logger.warning("No outputs to collect from cluster for job %s", job_id)
            return {}

        out_dir = Path(local_output)
        if not out_dir.is_dir():
            return {}

        files: dict[str, bytes] = {}
        for p in out_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(out_dir).as_posix()
                files[rel] = p.read_bytes()
        logger.info("Collected %d output file(s) from cluster for job %s", len(files), job_id)
        return files

    async def cleanup_container(self, job_id: str) -> None:
        """Clean up the remote work directory."""
        remote_work_dir = self._job_work_dirs.pop(job_id, "")
        if remote_work_dir:
            await self._ssh_run(f"rm -rf {shlex.quote(remote_work_dir)}")
            logger.debug("Cleaned up remote work dir %s", remote_work_dir)


def _memory_to_mb(mem: str) -> int:
    """Convert memory string (e.g. '4Gi', '512Mi', '2G') to megabytes."""
    mem = mem.strip()
    try:
        if mem.endswith("Gi"):
            return int(float(mem[:-2]) * 1024)
        if mem.endswith("Mi"):
            return int(float(mem[:-2]))
        if mem.endswith("G"):
            return int(float(mem[:-1]) * 1000)
        if mem.endswith("M"):
            return int(float(mem[:-1]))
        return int(mem)
    except (ValueError, TypeError):
        return 2048
