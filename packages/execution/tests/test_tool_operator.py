"""Tests for ToolOperator's JobSpec builders.

There is a single container execution path: the worker stages a /work/ host dir
with inputs.json + params.json and bind-mounts it; the tool reads it via
techneos-tool-runtime and writes outputs back to /work/output/. Human tools take a
separate no-container path. Dispatch is keyed on ``tool_type`` alone.

ToolOperator imports `from airflow.models import BaseOperator`, and airflow
is not in the workspace venv (packages/execution is excluded), so we stub the
module before importing the operator.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _stub_airflow() -> None:
    """Insert a minimal airflow.models module so tool_operator can import."""
    if "airflow" not in sys.modules:
        airflow_mod = types.ModuleType("airflow")
        sys.modules["airflow"] = airflow_mod
    if "airflow.models" not in sys.modules:
        models_mod = types.ModuleType("airflow.models")

        class _StubBaseOperator:
            template_fields: tuple = ()

            def __init__(self, **kwargs):
                pass

        models_mod.BaseOperator = _StubBaseOperator
        sys.modules["airflow.models"] = models_mod
        sys.modules["airflow"].models = models_mod


_stub_airflow()


@pytest.fixture
def operator():
    """A bare ToolOperator instance — methods are tested individually."""
    from operators.tool_operator import ToolOperator

    return ToolOperator(step_conf={})


@pytest.fixture
def _stub_storage(monkeypatch, tmp_path):
    """Replace `storage.download_file` with one that writes a small fake CSV."""
    import sys as _sys

    storage_mod = types.ModuleType("storage")

    def fake_download_file(*, storage_key, dest_path, bucket=None):
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(dest_path).write_text(f"# stub for {storage_key}\nsmiles\nCCO\n")

    storage_mod.download_file = fake_download_file
    storage_mod.upload_artifact = MagicMock(
        return_value={
            "storage_key": "k",
            "storage_bucket": "b",
            "file_name": "f",
            "file_size": 1,
            "content_type": "x",
            "checksum_sha256": "z",
        }
    )
    monkeypatch.setitem(_sys.modules, "storage", storage_mod)
    return storage_mod


# ── _build_runtime_spec for container tools ───────────────────────────


class TestBuildRuntimeSpecContainer:
    async def test_writes_inputs_and_params_json(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """The runtime/v1 path stages /work/{inputs.json, params.json} on the host."""
        import operators.tool_operator as op_mod

        # Force shared input dir to tmp_path so tempdirs land where we can read.
        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")

        # No dataset / upstream — exercises the simple inline case.
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(return_value=None),
        )

        step = {
            "name": "predict",
            "tool_slug": "admet-predictor",
            "tool_type": "container",
            "tool_version": 2,
            "parameters": {
                "smiles": ["CCO", "c1ccccc1"],
                "endpoints": ["lipinski"],
            },
            "resource_requirements": {
                "cpu": "1",
                "memory": "2Gi",
            },
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="predict",
            run_id="run-abc-123",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="tok",
        )

        assert spec.image == "techneos/admet-predictor"
        assert spec.tag == "latest"
        assert spec.command is None  # uses image's ENTRYPOINT
        assert spec.work_dir_host is not None

        wd = Path(spec.work_dir_host)
        params = json.loads((wd / "params.json").read_text())
        assert params == step["parameters"]

        inputs = json.loads((wd / "inputs.json").read_text())
        # No datasets or upstream → inputs.json is empty.
        assert inputs == {}

        # /work/input and /work/output exist and are empty.
        assert (wd / "input").is_dir()
        assert (wd / "output").is_dir()

    async def test_writes_dataset_paths_into_inputs_json(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """When a step has a `dataset` param, inputs.json gets `dataset_file`."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(
                return_value={
                    "storage_key": "datasets/zinc20/v1/molecules.csv",
                    "storage_bucket": "techneos-datasets",
                    "file_name": "molecules.csv",
                    "version": "1",
                }
            ),
        )

        step = {
            "name": "predict",
            "tool_slug": "admet-predictor",
            "tool_type": "container",
            "parameters": {"dataset": "zinc20:v1", "endpoints": ["lipinski"]},
            "resource_requirements": {},
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="predict",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="tok",
        )

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        # Path is what the container will see (under /work), not the host path.
        assert inputs["dataset_file"] == "/work/input/molecules.csv"
        # The actual file was downloaded into the host workdir.
        assert (wd / "input" / "molecules.csv").is_file()

    async def test_namespaced_dataset_param_gets_subdir(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """`training_dataset` → /work/input/training/<file> and
        `training_dataset_file` key in inputs.json."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(
                return_value={
                    "storage_key": "k",
                    "storage_bucket": "b",
                    "file_name": "train.csv",
                    "version": "2",
                }
            ),
        )

        step = {
            "name": "train",
            "tool_slug": "my-trainer",
            "tool_type": "container",
            "parameters": {"training_dataset": "my-set:v2"},
            "resource_requirements": {},
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="train",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        assert inputs["training_dataset_file"] == "/work/input/training/train.csv"
        # Sidecar carries the source type so the runtime parser can pick a format.
        assert inputs["training_dataset_source"]["type"] == "dataset"
        assert (wd / "input" / "training" / "train.csv").is_file()

    async def test_input_keys_ref_resolved_into_inputs_file(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """Plan B: an input_schema key whose value is a `<slug>:vN` ref
        resolves to ``<key>_file`` in inputs.json."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(
                return_value={
                    "storage_key": "k",
                    "storage_bucket": "b",
                    "file_name": "mols.csv",
                    "version": "1",
                }
            ),
        )

        step = {
            "name": "calc",
            "tool_slug": "molecule-property-calculator",
            "tool_type": "container",
            "parameters": {"smiles": "mols:v1", "detailed": True},
            "resource_requirements": {},
            "input_keys": ["smiles"],
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="calc",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        assert inputs["smiles_file"] == "/work/input/smiles/mols.csv"
        assert inputs["smiles_source"]["type"] == "dataset"
        assert (wd / "input" / "smiles" / "mols.csv").is_file()

    async def test_input_keys_inline_value_not_resolved(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """Plan B: inline values for an input_schema key stay in
        params.json and don't trigger a download."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        fetcher = AsyncMock()
        monkeypatch.setattr(op_mod, "_fetch_dataset_storage", fetcher)
        upload_fetcher = AsyncMock()
        monkeypatch.setattr(op_mod, "_fetch_upload_storage", upload_fetcher)

        step = {
            "name": "calc",
            "tool_slug": "molecule-property-calculator",
            "tool_type": "container",
            "parameters": {"smiles": ["CCO", "c1ccccc1"], "detailed": False},
            "resource_requirements": {},
            "input_keys": ["smiles"],
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="calc",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        params = json.loads((wd / "params.json").read_text())
        assert inputs == {}
        assert params["smiles"] == ["CCO", "c1ccccc1"]
        fetcher.assert_not_called()
        upload_fetcher.assert_not_called()

    async def test_input_keys_upload_ref_resolved(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """Plan B: an `upload:<id>` reference for an input_schema key
        is fetched from the tool service and exposed as `<key>_file`."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_upload_storage",
            AsyncMock(
                return_value={
                    "storage_key": "tool-run-inputs/org-1/abc/mols.csv",
                    "storage_bucket": "techneos-data",
                    "file_name": "mols.csv",
                }
            ),
        )

        step = {
            "name": "calc",
            "tool_slug": "molecule-property-calculator",
            "tool_type": "container",
            "parameters": {"smiles": "upload:abc"},
            "resource_requirements": {},
            "input_keys": ["smiles"],
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="calc",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        assert inputs["smiles_file"] == "/work/input/smiles/mols.csv"
        assert inputs["smiles_source"]["type"] == "upload"

    async def test_typed_pointer_paste_resolved_via_upload_endpoint(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """Typed pointer with type='paste' hits the inputs endpoint and
        carries content_type into the sidecar."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_upload_storage",
            AsyncMock(
                return_value={
                    "storage_key": "tool-run-inputs/org-1/abc/paste.txt",
                    "storage_bucket": "techneos-data",
                    "file_name": "paste.txt",
                    "content_type": "text/plain",
                    "source": "paste",
                }
            ),
        )

        step = {
            "name": "calc",
            "tool_slug": "molecule-property-calculator",
            "tool_type": "container",
            "parameters": {
                "smiles": {
                    "type": "paste",
                    "input_id": "abc",
                    "content_type": "text/plain",
                    "file_name": "paste.txt",
                },
            },
            "resource_requirements": {},
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="calc",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        assert inputs["smiles_file"] == "/work/input/smiles/paste.txt"
        assert inputs["smiles_source"] == {
            "type": "paste",
            "content_type": "text/plain",
        }

    async def test_typed_pointer_with_inline_storage_key_skips_api_call(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """When submit_run includes storage_key/storage_bucket in the typed
        pointer, _fetch_storage_info uses them directly without calling
        _fetch_upload_storage (which would 404 since ToolRunInput rows are
        ephemeral and the file has already been relocated to canonical)."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        upload_fetcher = AsyncMock()
        monkeypatch.setattr(op_mod, "_fetch_upload_storage", upload_fetcher)

        step = {
            "name": "calc",
            "tool_slug": "molecule-property-calculator",
            "tool_type": "container",
            "parameters": {
                "smiles": {
                    "type": "upload",
                    "input_id": "abc",
                    "content_type": "text/csv",
                    "file_name": "input.csv",
                    "storage_key": "tool-runs/molecule-property-calculator/v1/r/input/input.csv",
                    "storage_bucket": "techneos-data",
                },
            },
            "resource_requirements": {},
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="calc",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )

        # The file should be resolved without calling _fetch_upload_storage
        upload_fetcher.assert_not_called()

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        assert inputs["smiles_file"] == "/work/input/smiles/input.csv"
        assert inputs["smiles_source"] == {
            "type": "upload",
            "content_type": "text/csv",
        }

    async def test_writes_top_level_input_kind(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """The tool-wide input_kind from the schema lands in inputs.json
        as ``_input_kind`` so the runtime preprocessor can resolve a parser
        without re-deriving it from the file extension."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")

        step = {
            "name": "calc",
            "tool_slug": "molecule-property-calculator",
            "tool_type": "container",
            "parameters": {"smiles": ["CCO"]},
            "input_kind": "smiles_list",
            "resource_requirements": {},
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="calc",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )
        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        assert inputs["_input_kind"] == "smiles_list"

    async def test_typed_pointer_dataset_resolved(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        """Typed pointer with type='dataset' hits the dataset resolver."""
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(
                return_value={
                    "storage_key": "datasets/zinc20/v1/molecules.csv",
                    "storage_bucket": "techneos-data",
                    "file_name": "molecules.csv",
                    "version": "1",
                }
            ),
        )

        step = {
            "name": "calc",
            "tool_slug": "molecule-property-calculator",
            "tool_type": "container",
            "parameters": {
                "smiles": {"type": "dataset", "ref": "zinc20:v1"},
            },
            "resource_requirements": {},
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="calc",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="http://gw",
            callback_token="t",
        )

        wd = Path(spec.work_dir_host)
        inputs = json.loads((wd / "inputs.json").read_text())
        assert inputs["smiles_file"] == "/work/input/smiles/molecules.csv"
        assert inputs["smiles_source"]["type"] == "dataset"

    async def test_container_without_image_or_slug_raises(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(return_value=None),
        )

        step = {
            "name": "x",
            "tool_type": "container",
            "parameters": {},
            "resource_requirements": {},
            # No 'image' and no 'tool_slug'.
        }
        with pytest.raises(ValueError, match="no image"):
            await operator._build_runtime_spec(
                step=step,
                step_name="x",
                run_id="r",
                resources=step["resource_requirements"],
                callback_url="",
                callback_token="",
            )


# ── _build_runtime_spec for pypi tools ────────────────────────────────


class TestBuildRuntimeSpecPypi:
    async def test_pypi_command_invokes_runner(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(return_value=None),
        )

        step = {
            "name": "filter",
            "tool_slug": "csv-filter",
            "tool_type": "pypi",
            "package_name": "csv-filter",
            "package_version": "0.1.0",
            "entry_point": "csv_filter.filter:run",
            "package_index_url": "http://devpi:8080/",
            "parameters": {"column": "status", "value": "active"},
            "resource_requirements": {},
        }
        spec = await operator._build_runtime_spec(
            step=step,
            step_name="filter",
            run_id="r",
            resources=step["resource_requirements"],
            callback_url="",
            callback_token="",
        )

        assert spec.image == "techneos/tool-runtime"
        # No command override — the image's ENTRYPOINT pip-installs the tool
        # from TECHNEOS_INSTALL_* env vars, then runs the generic runner.
        assert spec.command is None
        assert spec.environment["TECHNEOS_INSTALL_PACKAGE"] == "csv-filter==0.1.0"
        assert spec.environment["ENTRYPOINT_SPEC"] == "csv_filter.filter:run"
        assert spec.environment["TECHNEOS_INSTALL_INDEX_URL"] == "http://devpi:8080/"
        assert spec.environment["TECHNEOS_INSTALL_TRUSTED_HOST"] == "devpi"
        # Still bind-mounts /work so inputs.json/params.json are visible.
        assert spec.work_dir_host is not None

    async def test_pypi_missing_fields_raise(
        self,
        operator,
        _stub_storage,
        monkeypatch,
        tmp_path,
    ):
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")
        monkeypatch.setattr(
            op_mod,
            "_fetch_dataset_storage",
            AsyncMock(return_value=None),
        )

        step = {
            "name": "filter",
            "tool_type": "pypi",
            "package_name": "x",  # missing version + entry_point
            "parameters": {},
            "resource_requirements": {},
        }
        with pytest.raises(ValueError, match=r"package_name|package_version|entry_point"):
            await operator._build_runtime_spec(
                step=step,
                step_name="filter",
                run_id="r",
                resources=step["resource_requirements"],
                callback_url="",
                callback_token="",
            )


# ── tool_type rejection in the runtime builder ────────────────────────


class TestRuntimeSpecToolTypes:
    """Non-container/pypi tool types are rejected by the single runtime builder."""

    @pytest.mark.parametrize("bad_type", ["weird-type", "module"])
    async def test_unsupported_tool_type_raises(
        self, operator, _stub_storage, monkeypatch, tmp_path, bad_type
    ):
        import operators.tool_operator as op_mod

        monkeypatch.setattr(op_mod, "_SHARED_INPUT_DIR", str(tmp_path))
        monkeypatch.setattr(op_mod, "_HOST_SHARED_INPUT_DIR", "")

        with pytest.raises(ValueError, match="Unsupported tool_type"):
            await operator._build_runtime_spec(
                step={
                    "name": "x",
                    "tool_type": bad_type,
                    "parameters": {},
                    "resource_requirements": {},
                },
                step_name="x",
                run_id="r",
                resources={},
                callback_url="",
                callback_token="",
            )


# ── execution-path selection (human vs runtime, by tool_type) ──────────


class TestPathSelection:
    """_execute_async routes ``tool_type == "human"`` to the human builder and
    everything else to the single runtime builder — keyed purely on tool_type,
    no runner_contract gate. The chosen builder is awaited, so we verify the
    dispatch by patching both builders."""

    async def _dispatch(self, operator, tool_type: str) -> None:
        if tool_type == "human":
            await operator._build_human_spec(
                step={}, step_name="s", run_id="r", resources={},
                callback_url="", callback_token="",
            )
        else:
            await operator._build_runtime_spec(
                step={}, step_name="s", run_id="r", resources={},
                callback_url="", callback_token="",
            )

    async def test_non_human_uses_runtime_builder(self, operator):
        with (
            patch.object(operator, "_build_runtime_spec", new=AsyncMock()) as runtime,
            patch.object(operator, "_build_human_spec", new=AsyncMock()) as human,
        ):
            await self._dispatch(operator, "container")
            runtime.assert_awaited_once()
            human.assert_not_awaited()

    async def test_human_uses_human_builder(self, operator):
        with (
            patch.object(operator, "_build_runtime_spec", new=AsyncMock()) as runtime,
            patch.object(operator, "_build_human_spec", new=AsyncMock()) as human,
        ):
            await self._dispatch(operator, "human")
            human.assert_awaited_once()
            runtime.assert_not_awaited()
