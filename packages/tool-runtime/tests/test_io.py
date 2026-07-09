"""Tests for techneos_tool_runtime.io — the helpers tool authors call directly."""

from __future__ import annotations

import json

import pytest

from techneos_tool_runtime.io import (
    WorkDir,
    artifact_path,
    read_inputs,
    read_params,
    write_artifact,
    write_result,
)


def test_workdir_from_env_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("TECHNEOS_WORK_DIR", raising=False)
    wd = WorkDir.from_env()
    assert wd.root.name == "work"  # /work


def test_workdir_from_env_honors_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    wd = WorkDir.from_env()
    assert wd.root == tmp_path


def test_workdir_ensure_creates_input_and_output(tmp_path):
    wd = WorkDir(root=tmp_path)
    wd.ensure()
    assert wd.input_dir.is_dir()
    assert wd.output_dir.is_dir()


def test_read_inputs_returns_empty_when_missing(tmp_path):
    wd = WorkDir(root=tmp_path)
    assert read_inputs(wd) == {}


def test_read_inputs_parses_json(tmp_path):
    wd = WorkDir(root=tmp_path)
    wd.ensure()
    wd.inputs_file.write_text(json.dumps({"dataset_file": "/work/input/x.csv"}))
    assert read_inputs(wd) == {"dataset_file": "/work/input/x.csv"}


def test_read_params_returns_empty_when_missing(tmp_path):
    wd = WorkDir(root=tmp_path)
    assert read_params(wd) == {}


def test_read_params_parses_json(tmp_path):
    wd = WorkDir(root=tmp_path)
    wd.ensure()
    wd.params_file.write_text(json.dumps({"threshold": 0.5}))
    assert read_params(wd) == {"threshold": 0.5}


def test_write_result_serialises_and_returns_path(tmp_path):
    wd = WorkDir(root=tmp_path)
    path = write_result({"count": 3, "items": ["a", "b"]}, work_dir=wd)
    assert path == wd.output_dir / "result.json"
    assert json.loads(path.read_text()) == {"count": 3, "items": ["a", "b"]}


def test_write_result_handles_non_json_native_with_default_str(tmp_path):
    """A tool might return e.g. Path objects — default=str keeps it from blowing up."""
    from pathlib import PurePosixPath

    wd = WorkDir(root=tmp_path)
    path = write_result({"file": PurePosixPath("/x/y.csv")}, work_dir=wd)
    assert json.loads(path.read_text())["file"] == "/x/y.csv"


def test_artifact_path_creates_output_dir(tmp_path):
    wd = WorkDir(root=tmp_path)
    p = artifact_path("predictions.csv", work_dir=wd)
    assert p == wd.output_dir / "predictions.csv"
    assert wd.output_dir.is_dir()


def test_artifact_path_rejects_traversal(tmp_path):
    wd = WorkDir(root=tmp_path)
    with pytest.raises(ValueError):
        artifact_path("../escape.txt", work_dir=wd)
    with pytest.raises(ValueError):
        artifact_path("subdir/file.txt", work_dir=wd)
    with pytest.raises(ValueError):
        artifact_path("..", work_dir=wd)


def test_write_artifact_text(tmp_path):
    wd = WorkDir(root=tmp_path)
    p = write_artifact("report.html", "<h1>Hi</h1>", work_dir=wd)
    assert p.read_text() == "<h1>Hi</h1>"


def test_write_artifact_bytes(tmp_path):
    wd = WorkDir(root=tmp_path)
    p = write_artifact("report.pdf", b"%PDF-1.4", work_dir=wd)
    assert p.read_bytes() == b"%PDF-1.4"
