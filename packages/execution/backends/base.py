"""Abstract base class for compute backends.

Each backend knows how to submit a containerised job, poll its status,
cancel it, and retrieve logs.  The ``ToolOperator`` selects a backend
based on the step's ``resource_requirements.backend`` field (falling
back to the ``COMPUTE_BACKEND`` environment variable).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class JobStatus(enum.StrEnum):
    """Normalised job status across all backends."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobResult:
    """Outcome of a submitted job."""

    job_id: str
    status: JobStatus = JobStatus.PENDING
    exit_code: int | None = None
    logs: str = ""
    outputs: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobSpec:
    """Everything a backend needs to run a job."""

    # Identity
    job_name: str
    run_id: str
    step_name: str

    # Container
    image: str
    tag: str = "latest"
    command: list[str] | None = None
    environment: dict[str, str] = field(default_factory=dict)

    # Resources
    cpu: str = "1"
    memory: str = "2Gi"
    gpu: int = 0

    # I/O: bind-mount the entire host work dir at /work (rw), so the container
    # reads inputs.json/params.json from /work and writes artifacts to
    # /work/output/. The backend collects outputs by reading the host dir
    # directly — no docker cp, no tar archive. Unset only for human steps,
    # which run no container.
    work_dir_host: str | None = None
    # Scheduler-local path to the same work dir (inside the Airflow container).
    # Backends that stage files (e.g. S3 upload for Batch) use this instead of
    # work_dir_host, which may be a host-translated path inaccessible from the
    # scheduler process.
    work_dir_local: str | None = None

    # Arbitrary backend-specific overrides
    extra: dict[str, Any] = field(default_factory=dict)


class ComputeBackend(ABC):
    """Interface every compute backend must implement."""

    @abstractmethod
    async def submit_job(self, spec: JobSpec) -> str:
        """Submit a job and return its backend-specific job id."""
        ...

    @abstractmethod
    async def get_job_status(self, job_id: str) -> JobResult:
        """Poll the current status of a previously submitted job."""
        ...

    @abstractmethod
    async def cancel_job(self, job_id: str) -> None:
        """Request cancellation of a running job."""
        ...

    @abstractmethod
    async def get_logs(self, job_id: str, tail: int = 500) -> str:
        """Return the last *tail* lines of log output."""
        ...

    async def collect_outputs(
        self,
        job_id: str,
        work_dir_host: str | None = None,
    ) -> dict[str, bytes]:
        """Collect output files from a completed job.

        *work_dir_host* points at the host directory bind-mounted at /work in
        the container — the backend reads ``{work_dir_host}/output/`` directly.

        Returns a mapping of ``filename → bytes``.  Backends that do not
        support output collection return an empty dict.
        """
        return {}

    async def cleanup_container(self, job_id: str) -> None:  # noqa: B027
        """Clean up resources after output collection.

        Optional hook with a default no-op — backends that leave no resources
        to reclaim (e.g. AWS Batch) simply don't override it, so it is
        intentionally concrete rather than abstract.
        """
