"""Tests for compute backend base classes and Docker/AWS Batch backends."""

from unittest.mock import MagicMock

import pytest

# We import from the worker package which lives outside the normal
# installed packages — tests rely on `uv run` which makes them available.


class TestJobSpec:
    """Test the JobSpec dataclass."""

    def test_defaults(self):
        from backends.base import JobSpec

        spec = JobSpec(
            job_name="test-job",
            run_id="run-1",
            step_name="dock",
            image="vina:latest",
        )
        assert spec.cpu == "1"
        assert spec.memory == "2Gi"
        assert spec.gpu == 0
        assert spec.environment == {}
        assert spec.work_dir_host is None

    def test_custom_resources(self):
        from backends.base import JobSpec

        spec = JobSpec(
            job_name="gpu-job",
            run_id="run-2",
            step_name="diffdock",
            image="diffdock:1.0",
            cpu="4",
            memory="16Gi",
            gpu=2,
        )
        assert spec.gpu == 2
        assert spec.memory == "16Gi"


class TestJobResult:
    """Test the JobResult dataclass."""

    def test_defaults(self):
        from backends.base import JobResult, JobStatus

        result = JobResult(job_id="j1")
        assert result.status == JobStatus.PENDING
        assert result.exit_code is None
        assert result.outputs == {}

    def test_failed_result(self):
        from backends.base import JobResult, JobStatus

        result = JobResult(
            job_id="j2",
            status=JobStatus.FAILED,
            exit_code=1,
            error_message="OOM killed",
        )
        assert result.status == JobStatus.FAILED
        assert result.error_message == "OOM killed"


class TestDockerBackendMemoryParsing:
    """Test the Docker backend's memory parsing helper."""

    def test_parse_gi(self):
        from backends.docker_backend import _parse_memory

        assert _parse_memory("4Gi") == 4 * 1024**3

    def test_parse_mi(self):
        from backends.docker_backend import _parse_memory

        assert _parse_memory("512Mi") == 512 * 1024**2

    def test_parse_g(self):
        from backends.docker_backend import _parse_memory

        assert _parse_memory("2G") == 2 * 1000**3

    def test_parse_invalid(self):
        from backends.docker_backend import _parse_memory

        assert _parse_memory("invalid") is None

    def test_parse_raw_bytes(self):
        from backends.docker_backend import _parse_memory

        assert _parse_memory("1073741824") == 1073741824


class TestDockerBackend:
    """Test DockerBackend with mocked Docker SDK."""

    @pytest.fixture
    def backend(self):
        from backends.docker_backend import DockerBackend

        b = DockerBackend()
        b._docker = MagicMock()
        return b

    async def test_submit_job(self, backend):
        from backends.base import JobSpec

        container = MagicMock()
        container.id = "abc123"
        backend._docker.images.pull = MagicMock()
        backend._docker.containers.run = MagicMock(return_value=container)

        spec = JobSpec(
            job_name="test",
            run_id="run-1",
            step_name="dock",
            image="vina",
            tag="latest",
        )
        job_id = await backend.submit_job(spec)
        assert job_id == "abc123"
        backend._docker.containers.run.assert_called_once()

    async def test_get_job_status_running(self, backend):
        from backends.base import JobStatus

        container = MagicMock()
        container.status = "running"
        container.attrs = {"State": {"ExitCode": None}}
        backend._docker.containers.get = MagicMock(return_value=container)

        result = await backend.get_job_status("abc123")
        assert result.status == JobStatus.RUNNING

    async def test_get_job_status_exited_success(self, backend):
        from backends.base import JobStatus

        container = MagicMock()
        container.status = "exited"
        container.attrs = {"State": {"ExitCode": 0}}
        backend._docker.containers.get = MagicMock(return_value=container)

        result = await backend.get_job_status("abc123")
        assert result.status == JobStatus.COMPLETED

    async def test_get_job_status_exited_failure(self, backend):
        from backends.base import JobStatus

        container = MagicMock()
        container.status = "exited"
        container.attrs = {"State": {"ExitCode": 137}}
        backend._docker.containers.get = MagicMock(return_value=container)

        result = await backend.get_job_status("abc123")
        assert result.status == JobStatus.FAILED
        assert result.exit_code == 137

    async def test_get_job_status_not_found(self, backend):
        from backends.base import JobStatus
        from docker.errors import NotFound

        backend._docker.containers.get = MagicMock(side_effect=NotFound("gone"))

        result = await backend.get_job_status("missing")
        assert result.status == JobStatus.FAILED
        assert "not found" in result.error_message.lower()

    async def test_cancel_job(self, backend):
        container = MagicMock()
        backend._docker.containers.get = MagicMock(return_value=container)

        await backend.cancel_job("abc123")
        container.stop.assert_called_once()
        container.remove.assert_called_once()

    async def test_get_logs(self, backend):
        container = MagicMock()
        container.logs.return_value = b"Running docking...\nDone."
        backend._docker.containers.get = MagicMock(return_value=container)

        logs = await backend.get_logs("abc123", tail=100)
        assert "Running docking" in logs


class TestAWSBatchBackendMemory:
    """Test AWS Batch memory conversion."""

    def test_memory_gi_to_mib(self):
        from backends.aws_batch_backend import _memory_to_mib

        assert _memory_to_mib("4Gi") == "4096"

    def test_memory_mi_to_mib(self):
        from backends.aws_batch_backend import _memory_to_mib

        assert _memory_to_mib("512Mi") == "512"

    def test_memory_fallback(self):
        from backends.aws_batch_backend import _memory_to_mib

        # Unrecognised suffix is returned as-is (assumed raw MiB string)
        assert _memory_to_mib("2048") == "2048"
        # Invalid numeric with known suffix falls back to default
        assert _memory_to_mib("badGi") == "2048"


class TestAWSBatchBackend:
    """Test AWSBatchBackend with mocked boto3."""

    @pytest.fixture
    def backend(self):
        from backends.aws_batch_backend import AWSBatchBackend

        b = AWSBatchBackend(
            job_queue="test-queue",
            job_definition="test-def",
            region="us-east-1",
        )
        b._batch = MagicMock()
        b._logs_client = MagicMock()
        return b

    async def test_submit_job(self, backend):
        from backends.base import JobSpec

        backend._batch.submit_job = MagicMock(return_value={"jobId": "aws-job-123"})
        # No job-definition revisions registered yet — resolve falls back to
        # the base job definition instead of registering an image-specific one.
        backend._batch.describe_job_definitions = MagicMock(
            return_value={"jobDefinitions": []}
        )

        spec = JobSpec(
            job_name="test",
            run_id="run-1",
            step_name="dock",
            image="vina",
            tag="latest",
            gpu=1,
        )
        job_id = await backend.submit_job(spec)
        assert job_id == "aws-job-123"
        backend._batch.submit_job.assert_called_once()

        # Verify GPU resource was included
        call_kwargs = backend._batch.submit_job.call_args[1]
        resource_reqs = call_kwargs["containerOverrides"]["resourceRequirements"]
        gpu_reqs = [r for r in resource_reqs if r["type"] == "GPU"]
        assert len(gpu_reqs) == 1
        assert gpu_reqs[0]["value"] == "1"

    async def test_get_job_status_running(self, backend):
        from backends.base import JobStatus

        backend._batch.describe_jobs = MagicMock(
            return_value={"jobs": [{"status": "RUNNING", "container": {}}]}
        )

        result = await backend.get_job_status("aws-job-123")
        assert result.status == JobStatus.RUNNING

    async def test_get_job_status_succeeded(self, backend):
        from backends.base import JobStatus

        backend._batch.describe_jobs = MagicMock(
            return_value={"jobs": [{"status": "SUCCEEDED", "container": {"exitCode": 0}}]}
        )

        result = await backend.get_job_status("aws-job-123")
        assert result.status == JobStatus.COMPLETED
        assert result.exit_code == 0

    async def test_get_job_status_not_found(self, backend):
        from backends.base import JobStatus

        backend._batch.describe_jobs = MagicMock(return_value={"jobs": []})

        result = await backend.get_job_status("missing")
        assert result.status == JobStatus.FAILED

    async def test_cancel_job(self, backend):
        backend._batch.terminate_job = MagicMock()

        await backend.cancel_job("aws-job-123")
        backend._batch.terminate_job.assert_called_once_with(
            jobId="aws-job-123", reason="Cancelled by platform"
        )


# ── runtime/v1 contract additions ────────────────────────────────────


class TestJobSpecRuntimeContract:
    """JobSpec carries a work_dir_host field for runtime/v1 tools."""

    def test_work_dir_host_defaults_to_none(self):
        from backends.base import JobSpec

        spec = JobSpec(job_name="j", run_id="r", step_name="s", image="img")
        assert spec.work_dir_host is None

    def test_work_dir_host_can_be_set(self):
        from backends.base import JobSpec

        spec = JobSpec(
            job_name="j",
            run_id="r",
            step_name="s",
            image="img",
            work_dir_host="/tmp/techneos-work-abc",
        )
        assert spec.work_dir_host == "/tmp/techneos-work-abc"


class TestDockerBackendRuntimeContract:
    """DockerBackend behaviour for tools using the runtime/v1 contract."""

    @pytest.fixture
    def backend(self):
        from backends.docker_backend import DockerBackend

        b = DockerBackend()
        b._docker = MagicMock()
        return b

    async def test_collect_outputs_reads_from_host_workdir(self, backend, tmp_path):
        """When work_dir_host is set, collect_outputs reads {host}/output/ directly,
        not via docker cp."""
        out = tmp_path / "output"
        out.mkdir()
        (out / "report.pdf").write_bytes(b"%PDF-1.7 stub")
        (out / "result.json").write_text('{"ok": true}')
        # subdirectory under output/ — collected with posix-style relative path
        sub = out / "plots"
        sub.mkdir()
        (sub / "mw.png").write_bytes(b"PNGDATA")

        files = await backend.collect_outputs(
            job_id="ignored-because-work-dir-set",
            work_dir_host=str(tmp_path),
        )
        # docker.containers.get must NOT have been called — we read from host
        backend._docker.containers.get.assert_not_called()
        assert set(files.keys()) == {"report.pdf", "result.json", "plots/mw.png"}
        assert files["report.pdf"] == b"%PDF-1.7 stub"
        assert files["result.json"] == b'{"ok": true}'

    async def test_collect_outputs_empty_when_no_output_dir(self, backend, tmp_path):
        files = await backend.collect_outputs(
            job_id="x",
            work_dir_host=str(tmp_path / "does-not-exist"),
        )
        assert files == {}

    async def test_collect_outputs_empty_without_workdir(self, backend):
        """No work_dir_host (e.g. a human step) → nothing to collect."""
        files = await backend.collect_outputs(job_id="job-1")
        assert files == {}

    async def test_submit_job_mounts_work_dir_rw(self, backend):
        """work_dir_host should produce a single rw bind mount at /work."""
        from backends.base import JobSpec

        container = MagicMock()
        container.id = "abc"
        backend._docker.images.pull = MagicMock()
        backend._docker.containers.run = MagicMock(return_value=container)
        backend._docker.containers.get = MagicMock(
            side_effect=__import__("docker").errors.NotFound("none")
        )

        spec = JobSpec(
            job_name="t",
            run_id="run-1",
            step_name="dock",
            image="techneos/admet-predictor",
            tag="2.0.0",
            work_dir_host="/host/work/abc",
        )
        await backend.submit_job(spec)

        kwargs = backend._docker.containers.run.call_args.kwargs
        volumes = kwargs.get("volumes", {})
        assert "/host/work/abc" in volumes
        assert volumes["/host/work/abc"] == {"bind": "/work", "mode": "rw"}
