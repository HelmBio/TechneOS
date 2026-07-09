"""I/O helpers for tool authors.

The runtime maintains a `WorkDir` rooted at /work/ inside containers (or any
caller-supplied directory when invoked in-process). The layout is fixed:

    {work_dir}/
        inputs.json          # resolved file paths + upstream artifact paths
        params.json          # step parameters
        input/               # bind-mounted dataset files + upstream artifacts
            {dataset_files}
            upstream/{step_name}/{filename}
        output/              # tools write here; worker collects everything
            result.json      # the dict returned by run(inputs, params)
            {artifact_files} # everything else the tool produced

Tool code should never hardcode `/work/...` paths. Use `write_artifact()` and
the paths handed to it via `inputs`. This keeps the same tool callable from
both the container path (work_dir=/work) and from in-process unit tests
(work_dir=tmp_path).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

# The container-side convention. The worker bind-mounts the host work dir here.
DEFAULT_WORK_DIR = Path("/work")


@dataclass(frozen=True)
class WorkDir:
    """A tool's view of its working directory.

    All paths are absolute. Use `from_env()` in the runner; pass an explicit
    root in unit tests.
    """

    root: Path

    @classmethod
    def from_env(cls) -> WorkDir:
        """Resolve the work dir from TECHNEOS_WORK_DIR or fall back to /work."""
        raw = os.environ.get("TECHNEOS_WORK_DIR", "")
        root = Path(raw) if raw else DEFAULT_WORK_DIR
        return cls(root=root)

    @property
    def inputs_file(self) -> Path:
        return self.root / "inputs.json"

    @property
    def params_file(self) -> Path:
        return self.root / "params.json"

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def result_file(self) -> Path:
        return self.output_dir / "result.json"

    def ensure(self) -> None:
        """Create the directory structure. Idempotent."""
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


# ── Top-level helpers — what tool authors actually call ───────────────


def read_inputs(work_dir: WorkDir | None = None) -> dict[str, Any]:
    """Load the resolved inputs dict written by the worker.

    Returns {} if inputs.json is absent (useful for tools that take no inputs).
    """
    wd = work_dir or WorkDir.from_env()
    if not wd.inputs_file.exists():
        return {}
    return cast(dict[str, Any], json.loads(wd.inputs_file.read_text()))


def read_params(work_dir: WorkDir | None = None) -> dict[str, Any]:
    """Load the step parameters written by the worker."""
    wd = work_dir or WorkDir.from_env()
    if not wd.params_file.exists():
        return {}
    return cast(dict[str, Any], json.loads(wd.params_file.read_text()))


def write_result(result: dict[str, Any], work_dir: WorkDir | None = None) -> Path:
    """Write the dict returned by run(...) to {work_dir}/output/result.json.

    Called by the runner — tool code should just return its dict.
    """
    wd = work_dir or WorkDir.from_env()
    wd.ensure()
    wd.result_file.write_text(json.dumps(result, indent=2, default=str))
    return wd.result_file


def artifact_path(name: str, work_dir: WorkDir | None = None) -> Path:
    """Return the absolute path a named artifact should be written to.

    Use this when a tool needs to hand a path to a library (e.g. matplotlib's
    `savefig`, pandas' `to_csv`) rather than bytes:

        from techneos_tool_runtime import artifact_path
        df.to_csv(artifact_path("predictions.csv"), index=False)
    """
    wd = work_dir or WorkDir.from_env()
    wd.ensure()
    # Reject path traversal — artifacts are flat under output/.
    if "/" in name or "\\" in name or name.startswith(".."):
        raise ValueError(f"artifact name must be a bare filename, got: {name!r}")
    return wd.output_dir / name


def write_artifact(
    name: str,
    data: bytes | str,
    work_dir: WorkDir | None = None,
) -> Path:
    """Write bytes or text to {work_dir}/output/{name} and return the path."""
    path = artifact_path(name, work_dir=work_dir)
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_bytes(data)
    return path
