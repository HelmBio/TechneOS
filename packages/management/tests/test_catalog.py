"""Tests for the catalog registration orchestrators (management.catalog).

These exercise ``read_package_meta`` for real against **synthetic**
catalog-shaped package dirs built in ``tmp_path`` — the real catalog packages
live in their own repo (extracted 2026-06-29), so management is tested here with
no dependency on catalog being present on disk.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from management import catalog
from management.registration import Session, read_package_meta


def _session(env_arg: str = "local") -> Session:
    return Session(
        env=MagicMock(), env_arg=env_arg, api_url="http://api",
        headers={"Authorization": "Bearer x"},
    )


def _resp(status: int = 200, json_data: dict | None = None):
    r = MagicMock()
    r.is_success = 200 <= status < 300
    r.status_code = status
    r.json.return_value = json_data or {}
    r.text = ""
    return r


def _write_pkg(
    base: Path,
    *,
    name: str,
    version: str = "0.1.0",
    entry_point: str | None = None,
    docker_image: str | None = None,
) -> Path:
    """Create a minimal catalog-shaped package dir (just enough for read_package_meta)."""
    base.mkdir(parents=True, exist_ok=True)
    techneos = ""
    if entry_point:
        techneos += f'entry_point = "{entry_point}"\n'
    if docker_image:
        techneos += f'docker_image = "{docker_image}"\n'
    (base / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n'
        + (f"\n[tool.techneos]\n{techneos}" if techneos else "")
    )
    return base


@pytest.fixture
def pkgs(tmp_path: Path):
    """Synthetic catalog package dirs mirroring the real catalog layout."""

    class _Pkgs:
        pypi_tool = _write_pkg(
            tmp_path / "tools/structure-alerts",
            name="structure-alerts",
            entry_point="structure_alerts.checker:run",
        )
        container_tool = _write_pkg(
            tmp_path / "tools/dataset-profiler",
            name="dataset-profiler",
            docker_image="techneos/dataset-profiler",
        )
        agent = _write_pkg(
            tmp_path / "agents/chembl",
            name="chembl-agent",
            entry_point="chembl_agent",
        )
        # task / pipeline / app are not Python packages — only _read_readme touches
        # these dirs, and it tolerates a missing README. Empty dirs suffice.
        task = tmp_path / "tasks/synthesis-request"
        pipeline = tmp_path / "pipelines/hit-triage"
        app = tmp_path / "apps/structure-viewer"

    for d in (_Pkgs.task, _Pkgs.pipeline, _Pkgs.app):
        d.mkdir(parents=True, exist_ok=True)
    return _Pkgs


class TestReadPackageMeta:
    def test_reads_name_version_entrypoint(self, pkgs):
        m = read_package_meta(pkgs.agent)
        assert (m.name, m.version, m.entry_point) == ("chembl-agent", "0.1.0", "chembl_agent")


class TestRecreateOrGet:
    def test_absent_returns_none(self):
        with patch.object(catalog, "find_resource_by_slug", return_value=None):
            assert catalog.recreate_or_get(_session(), "tools", "x", upsert=False) is None

    def test_exists_no_upsert_returns_id(self):
        with patch.object(catalog, "find_resource_by_slug", return_value="id-1"):
            assert catalog.recreate_or_get(_session(), "tools", "x", upsert=False) == "id-1"

    def test_exists_upsert_deletes_and_returns_none(self):
        with (
            patch.object(catalog, "find_resource_by_slug", return_value="id-1"),
            patch.object(catalog, "httpx") as hx,
        ):
            hx.delete.return_value = _resp(200)
            assert catalog.recreate_or_get(_session(), "tools", "x", upsert=True) is None
            hx.delete.assert_called_once()


class TestRegisterPypiTool:
    def test_creates_tool_then_version_with_wheel_recorded_first(self, pkgs):
        tool_def = {"name": "Structure Alerts", "slug": "structure-alerts", "tool_type": "pypi"}
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(catalog, "publish_wheel_and_record", return_value="0.1.0") as pub,
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.side_effect = [_resp(200, {"id": "tool-1"}), _resp(201, {"id": "ver-1"})]
            tool_id, version_id = catalog.register_pypi_tool(_session(), pkgs.pypi_tool, tool_def)

        assert (tool_id, version_id) == ("tool-1", "ver-1")
        pub.assert_called_once()  # wheel published + recorded
        assert pub.call_args.kwargs["origin"] == "catalog"
        # tool POST then version POST
        tool_body = hx.post.call_args_list[0].kwargs["json"]
        version_body = hx.post.call_args_list[1].kwargs["json"]
        assert tool_body["tool_type"] == "pypi"
        assert version_body["package_name"] == "structure-alerts"
        assert version_body["package_version"] == "0.1.0"

    def test_skip_build_does_not_publish(self, pkgs):
        tool_def = {"name": "Structure Alerts", "slug": "structure-alerts"}
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(catalog, "publish_wheel_and_record") as pub,
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.side_effect = [_resp(200, {"id": "tool-1"}), _resp(201, {"id": "ver-1"})]
            catalog.register_pypi_tool(_session(), pkgs.pypi_tool, tool_def, skip_build=True)
        pub.assert_not_called()


class TestRegisterContainerTool:
    def test_builds_image_then_creates_version(self, pkgs):
        tool_def = {"name": "Dataset Profiler", "slug": "dataset-profiler"}
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(
                catalog, "build_image_and_record", return_value="techneos/dataset-profiler"
            ) as bir,
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.side_effect = [_resp(200, {"id": "tool-1"}), _resp(201, {"id": "ver-1"})]
            tool_id, version_id = catalog.register_container_tool(
                _session("local"), pkgs.container_tool, tool_def
            )

        assert (tool_id, version_id) == ("tool-1", "ver-1")
        # image built+recorded via the shared helper (origin=catalog, fatal default)
        bir.assert_called_once()
        assert bir.call_args.kwargs["origin"] == "catalog"
        # version stores the returned image reference
        version_body = hx.post.call_args_list[1].kwargs["json"]
        assert version_body["docker_image"] == "techneos/dataset-profiler"
        assert version_body["docker_tag"] == "0.1.0"


class TestRegisterApp:
    def test_builds_image_upserts_app_and_deploys(self, pkgs):
        app_def = {"name": "Structure Viewer", "slug": "structure-viewer", "launch_mode": "embedded"}
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(
                catalog, "build_image_and_record", return_value="techneos/structure-viewer"
            ) as bir,
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.side_effect = [_resp(201, {"id": "app-1"}), _resp(200, {})]  # create + deploy
            app_id = catalog.register_app(_session("local"), pkgs.app, app_def, version="1.2.3")

        assert app_id == "app-1"
        # image recorded non-fatally (apps aren't hard-validated)
        assert bir.call_args.kwargs == {
            **bir.call_args.kwargs, "origin": "catalog", "fatal": False,
        }
        create_body = hx.post.call_args_list[0].kwargs["json"]
        assert create_body["docker_image"] == "techneos/structure-viewer"
        assert create_body["docker_tag"] == "1.2.3"
        # deploy triggered
        assert hx.post.call_args_list[1].args[0].endswith("/apps/app-1/deploy")

    def test_skip_deploy_does_not_deploy(self, pkgs):
        app_def = {"name": "Structure Viewer", "slug": "structure-viewer"}
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(catalog, "build_image_and_record", return_value="techneos/structure-viewer"),
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.return_value = _resp(201, {"id": "app-1"})
            catalog.register_app(
                _session("local"), pkgs.app, app_def, version="1.0.0", skip_deploy=True
            )
        assert hx.post.call_count == 1  # create only, no deploy


class TestRegisterTask:
    def test_human_task_upserts_tool_then_version_no_artifact(self, pkgs):
        task_def = {
            "name": "Synthesis Request",
            "slug": "synthesis-request",
            "human_config": {"assignment_type": "team", "due_in_hours": 72},
        }
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.side_effect = [_resp(200, {"id": "tool-1"}), _resp(201, {"id": "ver-1"})]
            tool_id, version_id = catalog.register_task(_session(), pkgs.task, task_def)

        assert (tool_id, version_id) == ("tool-1", "ver-1")
        tool_body = hx.post.call_args_list[0].kwargs["json"]
        version_body = hx.post.call_args_list[1].kwargs["json"]
        assert tool_body["tool_type"] == "human"  # a task is a human tool
        assert version_body["assignment_type"] == "team"
        assert version_body["due_in_hours"] == 72
        # no wheel/image fields on the version (no artifact)
        assert "package_name" not in version_body and "docker_image" not in version_body


class TestRegisterPipeline:
    def test_new_pipeline_posts_definition(self, pkgs):
        pipeline_def = {
            "name": "Hit Triage", "slug": "hit-triage",
            "steps": [{"tool_slug": "x"}], "edges": [],
        }
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.return_value = _resp(201, {"id": "pipe-1"})
            out = catalog.register_pipeline(_session(), pkgs.pipeline, pipeline_def)

        assert out == "pipe-1"
        body = hx.post.call_args.kwargs["json"]
        assert body["slug"] == "hit-triage" and body["steps"] == [{"tool_slug": "x"}]

    def test_existing_pipeline_no_upsert_returns_id_without_post(self, pkgs):
        with (
            patch.object(catalog, "find_resource_by_slug", return_value="pipe-9"),
            patch.object(catalog, "httpx") as hx,
        ):
            out = catalog.register_pipeline(
                _session(), pkgs.pipeline, {"name": "X", "slug": "hit-triage"}
            )
        assert out == "pipe-9"
        hx.post.assert_not_called()


class TestRegisterDataset:
    def test_creates_and_uploads(self, tmp_path):
        data_file = tmp_path / "d.tsv"
        data_file.write_text("a\tb\n1\t2\n")
        client = MagicMock()
        client.get.return_value = _resp(200, {"items": []})  # no existing dataset
        client.post.side_effect = [
            _resp(201, {"id": "ds-1", "slug": "zinc20", "is_public": True, "data_type": "x"}),
            _resp(201, {"version": 1, "status": "ready", "files": [{"file_size": 10}]}),
        ]
        with patch.object(catalog, "httpx") as hx:
            hx.Client.return_value.__enter__.return_value = client
            out = catalog.register_dataset(
                _session(), {"name": "ZINC20", "slug": "zinc20"}, data_file, upload_description="d"
            )
        assert out == "ds-1"
        assert client.post.call_count == 2  # create + upload
        assert client.post.call_args_list[0].kwargs["json"]["slug"] == "zinc20"
        assert "files" in client.post.call_args_list[1].kwargs  # multipart upload

    def test_existing_no_flags_is_noop(self, tmp_path):
        data_file = tmp_path / "d.tsv"
        data_file.write_text("a\n1\n")
        client = MagicMock()
        client.get.return_value = _resp(200, {"items": [{"id": "ds-9", "slug": "zinc20"}]})
        with patch.object(catalog, "httpx") as hx:
            hx.Client.return_value.__enter__.return_value = client
            out = catalog.register_dataset(
                _session(), {"name": "ZINC20", "slug": "zinc20"}, data_file
            )
        assert out == "ds-9"
        client.post.assert_not_called()  # no create / no upload


class TestRegisterAgent:
    def test_existing_agent_patches_model_and_package_config(self, pkgs):
        agent_def = {"slug": "chembl-research-assistant", "model_config": {"provider": "p"}}
        with (
            patch.object(catalog, "find_resource_by_slug", return_value="agent-1"),
            patch.object(catalog, "publish_wheel_and_record", return_value="0.1.0"),
            patch.object(catalog, "httpx") as hx,
        ):
            hx.patch.return_value = _resp(200, {"id": "agent-1"})
            out = catalog.register_agent(_session(), pkgs.agent, agent_def, upsert=False)

        assert out == "agent-1"
        hx.patch.assert_called_once()
        body = hx.patch.call_args.kwargs["json"]
        assert set(body) == {"model_config", "package_config"}
        assert body["package_config"] == {
            "name": "chembl-agent", "version": "0.1.0", "entry_point": "chembl_agent",
        }

    def test_new_agent_posts_full_definition(self, pkgs):
        agent_def = {"slug": "chembl-research-assistant", "model_config": {"provider": "p"}}
        with (
            patch.object(catalog, "find_resource_by_slug", return_value=None),
            patch.object(catalog, "publish_wheel_and_record", return_value="0.1.0"),
            patch.object(catalog, "httpx") as hx,
        ):
            hx.post.return_value = _resp(201, {"id": "agent-2"})
            out = catalog.register_agent(_session(), pkgs.agent, agent_def)

        assert out == "agent-2"
        body = hx.post.call_args.kwargs["json"]
        assert body["slug"] == "chembl-research-assistant"
        assert body["package_config"]["name"] == "chembl-agent"
