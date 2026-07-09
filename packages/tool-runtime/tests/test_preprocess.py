"""Tests for techneos_tool_runtime.runner._preprocess_inputs.

Exercises the path that converts ``{field}_file`` entries in inputs.json
into a parsed Python value under ``{field}``, using either the default
registry parser or a tool-supplied ``parse()`` function.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from techneos_tool_runtime.io import WorkDir
from techneos_tool_runtime.runner import (
    RunnerError,
    _preprocess_inputs,
    resolve_optional_attr,
    run_tool,
)


def _install_fake_tool(tmp_path, monkeypatch, module_name: str, body: str) -> None:
    pkg_dir = tmp_path / "fake_pkg"
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / f"{module_name}.py").write_text(textwrap.dedent(body))
    monkeypatch.syspath_prepend(str(pkg_dir))
    sys.modules.pop(module_name, None)


# ── resolve_optional_attr ──────────────────────────────────────────────


def test_resolve_optional_attr_returns_callable(tmp_path, monkeypatch):
    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_with_parse",
        """
        def run(inputs, params):
            return {}
        def parse(file_path, params):
            return [{"smiles": "from-tool"}]
        """,
    )
    parse_fn = resolve_optional_attr("fake_with_parse:run", "parse")
    assert callable(parse_fn)


def test_resolve_optional_attr_missing_returns_none(tmp_path, monkeypatch):
    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_without_parse",
        """
        def run(inputs, params):
            return {}
        """,
    )
    assert resolve_optional_attr("fake_without_parse:run", "parse") is None


# ── _preprocess_inputs ─────────────────────────────────────────────────


def test_preprocess_uses_default_parser(tmp_path):
    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("id,smiles\nmol-1,CCO\nmol-2,c1ccccc1\n")
    inputs = {
        "_input_kind": "smiles_list",
        "smiles_file": str(csv_path),
        "smiles_source": {"type": "upload", "content_type": "text/csv"},
    }
    result = _preprocess_inputs(inputs, params={}, tool_parse=None)
    assert result["smiles"] == [
        {"smiles": "CCO", "id": "mol-1"},
        {"smiles": "c1ccccc1", "id": "mol-2"},
    ]
    # Original sidecar keys remain available.
    assert result["smiles_file"] == str(csv_path)
    assert result["smiles_source"]["type"] == "upload"


def test_preprocess_legacy_inputs_without_kind_default_to_smiles_list(tmp_path):
    """Tools registered before input_kind landed still resolve via the registry default."""
    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("smiles\nCCO\n")
    inputs = {"smiles_file": str(csv_path)}
    result = _preprocess_inputs(inputs, params={}, tool_parse=None)
    assert result["smiles"] == [{"smiles": "CCO"}]


def test_preprocess_unknown_kind_raises_runner_error(tmp_path):
    """An explicit but unregistered kind should fail loud, not silently re-dispatch.

    This is the belt-and-suspenders layer: registration-time validation
    should have caught it, so reaching here means version drift or a DB
    rewrite. Either way, parsing a HELM polymer file as SMILES would
    produce garbage — better to stop with a clear message.
    """
    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("smiles\nCCO\n")
    inputs = {"_input_kind": "helm_list", "smiles_file": str(csv_path)}
    with pytest.raises(RunnerError, match=r"helm_list.*not in this runtime"):
        _preprocess_inputs(inputs, params={}, tool_parse=None)


def test_preprocess_calls_tool_parse_when_present(tmp_path):
    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("anything")

    def tool_parse(file_path, params):
        return [{"smiles": "from-tool-parse"}]

    inputs = {
        "smiles_file": str(csv_path),
        "smiles_source": {"type": "upload", "content_type": "text/csv"},
    }
    result = _preprocess_inputs(inputs, params={}, tool_parse=tool_parse)
    assert result["smiles"] == [{"smiles": "from-tool-parse"}]


def test_preprocess_handles_missing_source_sidecar(tmp_path):
    """Without a sidecar, the dispatcher falls back to file-extension detection."""
    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("smiles\nCCO\n")
    inputs = {"smiles_file": str(csv_path)}
    result = _preprocess_inputs(inputs, params={}, tool_parse=None)
    assert result["smiles"] == [{"smiles": "CCO"}]


def test_preprocess_paste_text_one_per_line(tmp_path):
    p = tmp_path / "paste.txt"
    p.write_text("CCO\nc1ccccc1\n")
    inputs = {
        "smiles_file": str(p),
        "smiles_source": {"type": "paste", "content_type": "text/plain"},
    }
    result = _preprocess_inputs(inputs, params={}, tool_parse=None)
    assert result["smiles"] == [{"smiles": "CCO"}, {"smiles": "c1ccccc1"}]


def test_preprocess_paste_json_list_of_strings(tmp_path):
    p = tmp_path / "paste.json"
    p.write_text('["CCO", "c1ccccc1"]')
    inputs = {
        "smiles_file": str(p),
        "smiles_source": {"type": "paste", "content_type": "application/json"},
    }
    result = _preprocess_inputs(inputs, params={}, tool_parse=None)
    assert result["smiles"] == [{"smiles": "CCO"}, {"smiles": "c1ccccc1"}]


def test_preprocess_multiple_fields(tmp_path):
    a = tmp_path / "a.csv"
    a.write_text("smiles\nCCO\n")
    b = tmp_path / "b.csv"
    b.write_text("smiles\nc1ccccc1\n")
    inputs = {
        "ligands_file": str(a),
        "ligands_source": {"type": "upload", "content_type": "text/csv"},
        "decoys_file": str(b),
        "decoys_source": {"type": "dataset", "content_type": "text/csv"},
    }
    result = _preprocess_inputs(inputs, params={}, tool_parse=None)
    assert result["ligands"] == [{"smiles": "CCO"}]
    assert result["decoys"] == [{"smiles": "c1ccccc1"}]


def test_preprocess_leaves_non_file_inputs_alone(tmp_path):
    inputs = {"some_other_key": "value"}
    result = _preprocess_inputs(inputs, params={}, tool_parse=None)
    assert result == {"some_other_key": "value"}


# ── end-to-end via run_tool ────────────────────────────────────────────


def test_run_tool_invokes_tool_supplied_parse(tmp_path, monkeypatch):
    """When a tool exports parse(), the runner uses it instead of the registry."""
    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("smiles\nignored\n")

    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_tool_with_parse",
        """
        def parse(file_path, params):
            return [{"smiles": "overridden", "id": "from-parse"}]
        def run(inputs, params):
            return {"smiles_seen": inputs.get("smiles", [])}
        """,
    )
    wd = WorkDir(root=tmp_path / "work")
    wd.ensure()
    wd.inputs_file.write_text(
        json.dumps(
            {
                "smiles_file": str(csv_path),
                "smiles_source": {"type": "upload", "content_type": "text/csv"},
            }
        )
    )
    wd.params_file.write_text("{}")

    result = run_tool("fake_tool_with_parse:run", work_dir=wd)
    assert result["smiles_seen"] == [{"smiles": "overridden", "id": "from-parse"}]


def test_run_tool_default_parser_when_no_tool_parse(tmp_path, monkeypatch):
    csv_path = tmp_path / "mols.csv"
    csv_path.write_text("id,smiles\nmol-1,CCO\n")

    _install_fake_tool(
        tmp_path,
        monkeypatch,
        "fake_tool_no_parse",
        """
        def run(inputs, params):
            return {"smiles_seen": inputs.get("smiles", [])}
        """,
    )
    wd = WorkDir(root=tmp_path / "work")
    wd.ensure()
    wd.inputs_file.write_text(
        json.dumps(
            {
                "smiles_file": str(csv_path),
                "smiles_source": {"type": "upload", "content_type": "text/csv"},
            }
        )
    )
    wd.params_file.write_text("{}")

    result = run_tool("fake_tool_no_parse:run", work_dir=wd)
    assert result["smiles_seen"] == [{"smiles": "CCO", "id": "mol-1"}]
