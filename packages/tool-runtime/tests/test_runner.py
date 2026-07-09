"""Tests for techneos_tool_runtime.runner — the generic entry point."""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from techneos_tool_runtime.io import WorkDir
from techneos_tool_runtime.runner import (
    RunnerError,
    _parse_entrypoint_spec,
    main,
    resolve_entrypoint,
    run_tool,
)

# ── _parse_entrypoint_spec ─────────────────────────────────────────────


def test_parse_entrypoint_spec_happy_path():
    assert _parse_entrypoint_spec("admet_predictor.core:run") == (
        "admet_predictor.core",
        "run",
    )


def test_parse_entrypoint_spec_rejects_no_colon():
    with pytest.raises(RunnerError, match="must be"):
        _parse_entrypoint_spec("admet_predictor.core.run")


def test_parse_entrypoint_spec_rejects_empty_halves():
    with pytest.raises(RunnerError, match="empty"):
        _parse_entrypoint_spec(":run")
    with pytest.raises(RunnerError, match="empty"):
        _parse_entrypoint_spec("admet_predictor.core:")


# ── resolve_entrypoint ─────────────────────────────────────────────────


def test_resolve_entrypoint_imports_callable():
    # json.dumps is a stable real callable to point at
    func = resolve_entrypoint("json:dumps")
    assert func is json.dumps


def test_resolve_entrypoint_missing_module():
    with pytest.raises(RunnerError, match="Could not import"):
        resolve_entrypoint("nonexistent_module_xyz:run")


def test_resolve_entrypoint_missing_attr():
    with pytest.raises(RunnerError, match="no attribute"):
        resolve_entrypoint("json:nonexistent_function")


def test_resolve_entrypoint_non_callable():
    with pytest.raises(RunnerError, match="non-callable"):
        # json.__name__ is a string attribute
        resolve_entrypoint("json:__name__")


# ── run_tool — happy path via a temp module ────────────────────────────


def _install_fake_tool(tmp_path, monkeypatch, module_name: str, body: str) -> None:
    """Drop a Python module on disk and add the dir to sys.path."""
    pkg_dir = tmp_path / "fake_pkg"
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / f"{module_name}.py").write_text(textwrap.dedent(body))
    monkeypatch.syspath_prepend(str(pkg_dir))
    # Ensure a previous import doesn't shadow us
    sys.modules.pop(module_name, None)


def test_run_tool_writes_result(tmp_path, monkeypatch):
    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_tool_happy",
        """
        def run(inputs, params):
            return {"echo_inputs": inputs, "echo_params": params, "ok": True}
        """,
    )
    wd = WorkDir(root=tmp_path / "work")
    wd.ensure()
    wd.inputs_file.write_text(json.dumps({"k": "v"}))
    wd.params_file.write_text(json.dumps({"p": 1}))

    result = run_tool("fake_tool_happy:run", work_dir=wd)

    assert result == {"echo_inputs": {"k": "v"}, "echo_params": {"p": 1}, "ok": True}
    on_disk = json.loads(wd.result_file.read_text())
    assert on_disk == result


def test_run_tool_rejects_non_dict_return(tmp_path, monkeypatch):
    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_tool_bad_return",
        """
        def run(inputs, params):
            return [1, 2, 3]  # not a dict
        """,
    )
    wd = WorkDir(root=tmp_path / "work")
    wd.ensure()
    wd.inputs_file.write_text("{}")
    wd.params_file.write_text("{}")

    with pytest.raises(RunnerError, match="expected dict"):
        run_tool("fake_tool_bad_return:run", work_dir=wd)


def test_run_tool_handles_missing_input_files(tmp_path, monkeypatch):
    """A tool with no upstream inputs should still be callable."""
    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_tool_empty",
        """
        def run(inputs, params):
            return {"got_inputs": inputs, "got_params": params}
        """,
    )
    wd = WorkDir(root=tmp_path / "work")
    # NOTE: do not write inputs.json / params.json

    result = run_tool("fake_tool_empty:run", work_dir=wd)
    assert result == {"got_inputs": {}, "got_params": {}}


# ── main() — exit codes and error.json ─────────────────────────────────


def test_main_returns_2_without_entrypoint(monkeypatch, tmp_path):
    monkeypatch.delenv("ENTRYPOINT_SPEC", raising=False)
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    assert main([]) == 2


def test_main_returns_3_on_runner_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    rc = main(["--entrypoint", "nonexistent_module_xyz:run"])
    assert rc == 3
    err = json.loads((tmp_path / "output" / "error.json").read_text())
    assert err["type"] == "runner_error"
    assert "Could not import" in err["message"]


def test_main_returns_1_on_tool_exception(monkeypatch, tmp_path):
    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_tool_raises",
        """
        def run(inputs, params):
            raise RuntimeError("intentional boom")
        """,
    )
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    rc = main(["--entrypoint", "fake_tool_raises:run"])
    assert rc == 1
    err = json.loads((tmp_path / "output" / "error.json").read_text())
    assert err["type"] == "RuntimeError"
    assert err["message"] == "intentional boom"
    assert "traceback" in err


def test_main_returns_0_on_success(monkeypatch, tmp_path):
    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_tool_main_ok",
        """
        def run(inputs, params):
            return {"status": "ok"}
        """,
    )
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    rc = main(["--entrypoint", "fake_tool_main_ok:run"])
    assert rc == 0
    assert json.loads((tmp_path / "output" / "result.json").read_text()) == {"status": "ok"}
