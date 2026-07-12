"""Tests for the Slurm HPC compute backend."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from backends.base import JobSpec, JobStatus
from backends.slurm_backend import SlurmBackend, _memory_to_mb

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def spec() -> JobSpec:
    return JobSpec(
        job_name="techneos-abc12345-dock",
        run_id="abc12345-6789-0000-0000-000000000000",
        step_name="dock",
        image="techneos/autodock-vina",
        tag="0.1.0",
        cpu="4",
        memory="8Gi",
        gpu=1,
        work_dir_host="/tmp/techneos-work-dock-xyz",
        environment={"TECHNEOS_RUN_ID": "abc12345", "TECHNEOS_STEP_NAME": "dock"},
        extra={"partition": "gpu", "account": "drug-disc", "time_limit": "2:00:00"},
    )


@pytest.fixture
def backend() -> SlurmBackend:
    return SlurmBackend(
        submit_host="hpc-login.example.com",
        ssh_user="techneos-svc",
        ssh_key_path="/home/techneos/.ssh/id_rsa",
        partition="default",
        work_dir="/scratch/techneos",
        singularity_cache="/scratch/techneos/sif-cache",
    )


# ── _memory_to_mb ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "input_val,expected",
    [
        ("4Gi", 4096),
        ("512Mi", 512),
        ("2G", 2000),
        ("256M", 256),
        ("1024", 1024),
        ("garbage", 2048),
    ],
)
def test_memory_to_mb(input_val: str, expected: int) -> None:
    assert _memory_to_mb(input_val) == expected


# ── SIF path derivation ─────────────────────────────────────────────


def test_sif_path(backend: SlurmBackend) -> None:
    sif = backend._sif_path("techneos/autodock-vina", "0.1.0")
    assert sif == "/scratch/techneos/sif-cache/techneos_autodock-vina_0.1.0.sif"


def test_sif_path_ecr(backend: SlurmBackend) -> None:
    sif = backend._sif_path("123456789.dkr.ecr.us-east-1.amazonaws.com/techneos/vina", "1.0")
    assert sif.endswith(".sif")
    assert "/" not in sif.split("/")[-1].replace("_", "")  # no slashes in filename


# ── submit_job ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_job_calls_sbatch(backend: SlurmBackend, spec: JobSpec) -> None:
    ssh_calls: list[str] = []

    async def fake_ssh_run(cmd: str) -> tuple[int, str, str]:
        ssh_calls.append(cmd)
        if "sbatch" in cmd:
            return 0, "12345", ""
        return 0, "", ""

    async def fake_rsync_to(local: str, remote: str) -> None:
        pass

    async def fake_ensure_sif(image: str, tag: str) -> str:
        return f"/scratch/techneos/sif-cache/{image}_{tag}.sif"

    backend._ssh_run = fake_ssh_run  # type: ignore[assignment]
    backend._rsync_to_cluster = fake_rsync_to  # type: ignore[assignment]
    backend._ensure_sif_image = fake_ensure_sif  # type: ignore[assignment]

    job_id = await backend.submit_job(spec)

    assert job_id == "12345"
    assert backend._job_work_dirs["12345"].startswith("/scratch/techneos/runs/")
    # Should have called mkdir, write script, and sbatch
    assert any("mkdir" in c for c in ssh_calls)
    assert any("sbatch" in c for c in ssh_calls)


@pytest.mark.asyncio
async def test_submit_job_raises_on_failure(backend: SlurmBackend, spec: JobSpec) -> None:
    async def fail_ssh(cmd: str) -> tuple[int, str, str]:
        if "sbatch" in cmd:
            return 1, "", "sbatch: error: invalid partition"
        return 0, "", ""

    async def noop_rsync(local: str, remote: str) -> None:
        pass

    async def fake_ensure_sif(image: str, tag: str) -> str:
        return "/cache/img.sif"

    backend._ssh_run = fail_ssh  # type: ignore[assignment]
    backend._rsync_to_cluster = noop_rsync  # type: ignore[assignment]
    backend._ensure_sif_image = fake_ensure_sif  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="sbatch failed"):
        await backend.submit_job(spec)


# ── get_job_status ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sacct_output,expected_status",
    [
        ("COMPLETED|0:0", JobStatus.COMPLETED),
        ("RUNNING|0:0", JobStatus.RUNNING),
        ("PENDING|0:0", JobStatus.PENDING),
        ("FAILED|1:0", JobStatus.FAILED),
        ("CANCELLED+|0:0", JobStatus.CANCELLED),
        ("TIMEOUT|0:0", JobStatus.FAILED),
        ("OUT_OF_MEMORY|0:0", JobStatus.FAILED),
    ],
)
async def test_get_job_status_sacct(
    backend: SlurmBackend, sacct_output: str, expected_status: JobStatus
) -> None:
    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        if "sacct" in cmd:
            return 0, sacct_output, ""
        return 1, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    result = await backend.get_job_status("12345")
    assert result.status == expected_status


@pytest.mark.asyncio
async def test_get_job_status_falls_back_to_squeue(backend: SlurmBackend) -> None:
    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        if "sacct" in cmd:
            return 1, "", "sacct not available"
        if "squeue" in cmd:
            return 0, "RUNNING", ""
        return 1, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    result = await backend.get_job_status("12345")
    assert result.status == JobStatus.RUNNING


# ── cancel_job ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_job(backend: SlurmBackend) -> None:
    cancelled = False

    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        nonlocal cancelled
        if "scancel" in cmd:
            cancelled = True
            assert "99999" in cmd
        return 0, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    await backend.cancel_job("99999")
    assert cancelled


# ── get_logs ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_logs(backend: SlurmBackend) -> None:
    backend._job_work_dirs["12345"] = "/scratch/techneos/runs/abc/dock"

    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        if "slurm-12345.out" in cmd:
            return 0, "line 1\nline 2", ""
        if "slurm-12345.err" in cmd:
            return 0, "warning: something", ""
        return 0, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    logs = await backend.get_logs("12345", tail=100)
    assert "line 1" in logs
    assert "stderr" in logs
    assert "warning: something" in logs


@pytest.mark.asyncio
async def test_get_logs_no_workdir(backend: SlurmBackend) -> None:
    logs = await backend.get_logs("99999")
    assert logs == ""


# ── collect_outputs ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_collect_outputs(backend: SlurmBackend, tmp_path: object) -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as work_dir:
        wd = Path(work_dir)
        out_dir = wd / "output"
        out_dir.mkdir()
        (out_dir / "result.csv").write_text("col1,col2\n1,2")
        (out_dir / "plots").mkdir()
        (out_dir / "plots" / "fig.png").write_bytes(b"\x89PNG")

        backend._job_work_dirs["12345"] = "/scratch/techneos/runs/abc/dock"

        async def fake_rsync(remote: str, local: str) -> None:
            # Already populated by the test setup
            pass

        backend._rsync_from_cluster = fake_rsync  # type: ignore[assignment]
        files = await backend.collect_outputs("12345", work_dir_host=work_dir)

        assert "result.csv" in files
        assert "plots/fig.png" in files
        assert files["plots/fig.png"] == b"\x89PNG"


# ── cleanup_container ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_removes_remote_dir(backend: SlurmBackend) -> None:
    backend._job_work_dirs["12345"] = "/scratch/techneos/runs/abc/dock"
    rm_called = False

    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        nonlocal rm_called
        if "rm -rf" in cmd:
            rm_called = True
            assert "/scratch/techneos/runs/abc/dock" in cmd
        return 0, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    await backend.cleanup_container("12345")
    assert rm_called
    assert "12345" not in backend._job_work_dirs


# ── ensure_sif_image ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_sif_cached(backend: SlurmBackend) -> None:
    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        if "test -f" in cmd:
            return 0, "exists", ""
        return 0, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    sif = await backend._ensure_sif_image("techneos/vina", "0.1.0")
    assert sif.endswith(".sif")


@pytest.mark.asyncio
async def test_ensure_sif_pulls_when_missing(backend: SlurmBackend) -> None:
    pulled = False

    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        nonlocal pulled
        if "test -f" in cmd:
            return 1, "", ""
        if "singularity pull" in cmd:
            pulled = True
            return 0, "", ""
        return 0, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    await backend._ensure_sif_image("techneos/vina", "0.1.0")
    assert pulled


@pytest.mark.asyncio
async def test_ensure_sif_always_repulls_latest(backend: SlurmBackend) -> None:
    pulled = False

    async def fake_ssh(cmd: str) -> tuple[int, str, str]:
        nonlocal pulled
        if "test -f" in cmd:
            return 0, "exists", ""
        if "singularity pull" in cmd:
            pulled = True
            return 0, "", ""
        return 0, "", ""

    backend._ssh_run = fake_ssh  # type: ignore[assignment]
    await backend._ensure_sif_image("techneos/vina", "latest")
    assert pulled


# ── Constructor validation ───────────────────────────────────────────


def test_missing_submit_host_raises() -> None:
    with patch.dict("os.environ", {}, clear=False):
        if "SLURM_SUBMIT_HOST" in __import__("os").environ:
            return  # can't test if env var is set
        with pytest.raises(ValueError, match="SLURM_SUBMIT_HOST"):
            SlurmBackend(submit_host="")
