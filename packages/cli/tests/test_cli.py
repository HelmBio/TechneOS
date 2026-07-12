"""Unit tests for the CLI client.

Tests use typer.testing.CliRunner and mock httpx responses.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from cli import app
from cli.client import ApiError

runner = CliRunner()


# ── Helpers ────────────────────────────────────────────────────


def _mock_response(
    status_code: int = 200, json_data: dict | None = None, text: str = ""
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or json.dumps(json_data or {})
    resp.json.return_value = json_data or {}
    return resp


# ── Version / Health ───────────────────────────────────────────


class TestRootCommands:
    def test_version(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "techneos-cli" in result.output

    @patch("cli.config.get_base_url", return_value="http://test:8000")
    @patch("httpx.get")
    def test_health_ok(self, mock_get, _):
        mock_get.return_value = _mock_response(200, {"status": "ok"})
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "ok" in result.output

    @patch("cli.config.get_base_url", return_value="http://test:8000")
    @patch("httpx.get", side_effect=__import__("httpx").ConnectError("refused"))
    def test_health_unreachable(self, mock_get, _):
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 1
        assert "Cannot connect" in result.output


# ── Config ─────────────────────────────────────────────────────


class TestConfig:
    def test_save_and_load_tokens(self, tmp_path):
        with (
            patch("cli.config.CONFIG_DIR", tmp_path),
            patch("cli.config.TOKEN_FILE", tmp_path / "token.json"),
        ):
            from cli.config import clear_tokens, load_tokens, save_tokens

            assert load_tokens() is None
            save_tokens("access123", "refresh456")
            tokens = load_tokens()
            assert tokens["access_token"] == "access123"
            assert tokens["refresh_token"] == "refresh456"
            clear_tokens()
            assert load_tokens() is None

    def test_base_url_default(self, tmp_path):
        with patch("cli.config.CONFIG_FILE", tmp_path / "config.json"):
            from cli.config import get_base_url

            assert get_base_url() == "http://localhost:8000"

    def test_set_and_get_base_url(self, tmp_path):
        with (
            patch("cli.config.CONFIG_DIR", tmp_path),
            patch("cli.config.CONFIG_FILE", tmp_path / "config.json"),
        ):
            from cli.config import get_base_url, set_base_url

            set_base_url("http://myplatform:9000/")
            assert get_base_url() == "http://myplatform:9000"


# ── Client ─────────────────────────────────────────────────────


class TestClient:
    def test_api_error_repr(self):
        from cli.client import ApiError

        e = ApiError(404, "not found")
        assert "404" in str(e)
        assert "not found" in str(e)

    def test_handle_response_success(self):
        from cli.client import _handle_response

        resp = _mock_response(200, {"ok": True})
        assert _handle_response(resp) is resp

    def test_handle_response_401(self):
        from cli.client import ApiError, _handle_response

        resp = _mock_response(401)
        with pytest.raises(ApiError, match="Unauthorized"):
            _handle_response(resp)

    def test_handle_response_403(self):
        from cli.client import ApiError, _handle_response

        resp = _mock_response(403)
        with pytest.raises(ApiError, match="Forbidden"):
            _handle_response(resp)

    def test_handle_response_404(self):
        from cli.client import ApiError, _handle_response

        resp = _mock_response(404, {"detail": "Dataset 'x' not found"})
        with pytest.raises(ApiError, match="Dataset"):
            _handle_response(resp)

    def test_require_auth_not_logged_in(self):
        import typer

        with patch("cli.client.load_tokens", return_value=None):
            from cli.client import require_auth

            with pytest.raises(typer.Exit):
                require_auth()


# ── Auth commands ──────────────────────────────────────────────


class TestAuthCommands:
    @patch("cli.commands.auth.api_post")
    @patch("cli.commands.auth.save_tokens")
    def test_login_success(self, mock_save, mock_post):
        mock_post.return_value = {
            "access_token": "tok123",
            "refresh_token": "ref456",
        }
        result = runner.invoke(
            app,
            ["auth", "login", "--email", "user@test.com", "--password", "pass123"],
        )
        assert result.exit_code == 0
        assert "Logged in" in result.output
        mock_save.assert_called_once_with("tok123", "ref456")

    @patch("cli.commands.auth.api_post")
    def test_login_failure(self, mock_post):
        from cli.client import ApiError

        mock_post.side_effect = ApiError(401, "Invalid credentials")
        result = runner.invoke(
            app,
            ["auth", "login", "--email", "bad@test.com", "--password", "wrong"],
        )
        assert result.exit_code == 1
        assert "Invalid credentials" in result.output

    @patch("cli.commands.auth.clear_tokens")
    def test_logout(self, mock_clear):
        result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output
        mock_clear.assert_called_once()

    @patch("cli.commands.auth.api_get")
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    def test_whoami(self, _, mock_get):
        mock_get.return_value = {
            "id": "u1",
            "email": "me@test.com",
            "full_name": "Test User",
            "is_active": True,
            "org_id": "org1",
            "role_id": "r1",
        }
        result = runner.invoke(app, ["auth", "whoami"])
        assert result.exit_code == 0
        assert "me@test.com" in result.output

    @patch("cli.config.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.config.get_base_url", return_value="http://localhost:8000")
    def test_status_logged_in(self, _, __):
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "True" in result.output or "true" in result.output.lower()


# ── Dataset commands ───────────────────────────────────────────


class TestDatasetCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.datasets.api_get")
    def test_list_datasets(self, mock_get, _):
        mock_get.return_value = {
            "items": [
                {
                    "id": "d" * 36,
                    "name": "ChEMBL",
                    "data_type": "molecular",
                    "is_public": False,
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
            "total": 1,
            "skip": 0,
            "limit": 20,
        }
        result = runner.invoke(app, ["dataset", "list"])
        assert result.exit_code == 0
        assert "ChEMBL" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.datasets.api_get")
    def test_list_datasets_empty(self, mock_get, _):
        mock_get.return_value = {"items": [], "total": 0, "skip": 0, "limit": 20}
        result = runner.invoke(app, ["dataset", "list"])
        assert result.exit_code == 0
        assert "No datasets" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.datasets.api_post")
    def test_create_dataset(self, mock_post, _):
        mock_post.return_value = {
            "id": "d1",
            "name": "Test",
            "slug": "test",
            "data_type": "tabular",
            "is_public": False,
            "org_id": "o1",
            "created_by": "u1",
            "tags": [],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        result = runner.invoke(
            app,
            [
                "dataset",
                "create",
                "--name",
                "Test",
                "--slug",
                "test",
                "--data-schema",
                '{"type": "object", "properties": {"id": {"type": "string"}}}',
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Created dataset" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.datasets.api_delete")
    def test_delete_dataset(self, mock_del, _):
        result = runner.invoke(app, ["dataset", "delete", "d1", "--yes"])
        assert result.exit_code == 0
        assert "Deleted" in result.output


# ── Tool commands ──────────────────────────────────────────────


class TestToolCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.tools.api_get")
    def test_list_tools(self, mock_get, _):
        mock_get.return_value = {
            "items": [
                {
                    "id": "t" * 36,
                    "name": "AutoDock",
                    "category": "docking",
                    "is_public": True,
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
            "total": 1,
            "skip": 0,
            "limit": 20,
        }
        result = runner.invoke(app, ["tool", "list"])
        assert result.exit_code == 0
        assert "AutoDock" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.tools.api_post")
    def test_register_tool(self, mock_post, _):
        mock_post.return_value = {
            "id": "t1",
            "name": "MyTool",
            "slug": "my-tool",
            "category": "general",
            "is_public": False,
            "org_id": "o1",
            "created_by": "u1",
            "tags": [],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        result = runner.invoke(
            app,
            ["tool", "register", "--name", "MyTool", "--slug", "my-tool"],
        )
        assert result.exit_code == 0
        assert "Registered tool" in result.output


# ── Pipeline commands ──────────────────────────────────────────


class TestPipelineCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.pipelines.api_get")
    def test_list_pipelines(self, mock_get, _):
        mock_get.return_value = {
            "items": [
                {
                    "id": "p" * 36,
                    "name": "Virtual Screening",
                    "version": 1,
                    "steps": [{"name": "prep"}, {"name": "dock"}],
                    "is_public": False,
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
            "total": 1,
            "skip": 0,
            "limit": 20,
        }
        result = runner.invoke(app, ["pipeline", "list"])
        assert result.exit_code == 0
        assert "Virtual" in result.output
        assert "Screening" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.pipelines.api_post")
    def test_create_pipeline(self, mock_post, _, tmp_path):
        mock_post.return_value = {
            "id": "p1",
            "name": "Test Pipeline",
            "slug": "test-pipeline",
            "version": 1,
            "steps": [{"name": "step1", "tool_slug": "tool1"}],
            "edges": [],
            "parameters_schema": {},
            "default_parameters": {},
            "tags": [],
            "is_public": False,
            "org_id": "o1",
            "created_by": "u1",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        pipeline_file = tmp_path / "pipeline.json"
        pipeline_file.write_text(
            json.dumps(
                {
                    "name": "Test Pipeline",
                    "slug": "test-pipeline",
                    "steps": [{"name": "step1", "tool_slug": "tool1"}],
                }
            )
        )
        result = runner.invoke(app, ["pipeline", "create", str(pipeline_file)])
        assert result.exit_code == 0
        assert "Created pipeline" in result.output


# ── Run commands ───────────────────────────────────────────────


class TestRunCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.pipelines.api_post")
    def test_submit_run(self, mock_post, _):
        mock_post.return_value = {
            "id": "r1",
            "pipeline_id": "p1",
            "status": "pending",
            "parameters": {"receptor": "target.pdbqt"},
            "org_id": "o1",
            "submitted_by": "u1",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        result = runner.invoke(
            app,
            ["pipeline-run", "submit", "p1", "--params", '{"receptor": "target.pdbqt"}'],
        )
        assert result.exit_code == 0
        assert "Submitted run" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.pipelines.api_get")
    def test_list_runs(self, mock_get, _):
        mock_get.return_value = {
            "items": [
                {
                    "id": "r" * 36,
                    "pipeline_id": "p" * 36,
                    "status": "completed",
                    "created_at": "2026-01-01T00:00:00",
                    "started_at": "2026-01-01T00:01:00",
                    "finished_at": "2026-01-01T00:05:00",
                }
            ],
            "total": 1,
            "skip": 0,
            "limit": 20,
        }
        result = runner.invoke(app, ["pipeline-run", "list"])
        assert result.exit_code == 0
        assert "completed" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.pipelines.api_post")
    def test_cancel_run(self, mock_post, _):
        mock_post.return_value = {"id": "r1", "status": "cancelled"}
        result = runner.invoke(app, ["pipeline-run", "cancel", "r1"])
        assert result.exit_code == 0
        assert "cancelled" in result.output


# ── Output formatting ─────────────────────────────────────────


class TestOutput:
    def test_json_mode(self, capsys):
        from cli.output import is_json_mode, set_json_mode

        set_json_mode(True)
        assert is_json_mode()
        set_json_mode(False)
        assert not is_json_mode()

    def test_fmt_size(self):
        from cli.commands.datasets import _fmt_size

        assert _fmt_size(500) == "500 B"
        assert _fmt_size(1024) == "1 KB"
        assert _fmt_size(1048576) == "1 MB"


# ── Agent commands ─────────────────────────────────────────────


class TestAgentCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.agents.api_get")
    def test_list_agents(self, mock_get, _):
        mock_get.return_value = {
            "items": [{
                "id": "a" * 36, "name": "Triage Bot", "agent_type": "assistant",
                "is_public": True, "created_at": "2026-01-01T00:00:00",
            }],
            "total": 1,
        }
        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "Triage Bot" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.agents.api_get")
    def test_list_agents_empty(self, mock_get, _):
        mock_get.return_value = {"items": [], "total": 0}
        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "No agents found." in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.agents.api_get")
    def test_get_agent(self, mock_get, _):
        mock_get.return_value = {"id": "a1", "name": "Triage Bot", "slug": "triage"}
        result = runner.invoke(app, ["agent", "get", "triage"])
        assert result.exit_code == 0
        mock_get.assert_called_once_with("/api/v1/agents/triage")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.agents.api_get", side_effect=ApiError(404, "not found"))
    def test_get_agent_not_found(self, mock_get, _):
        result = runner.invoke(app, ["agent", "get", "missing"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.agents.api_delete")
    def test_delete_agent_with_yes(self, mock_del, _):
        result = runner.invoke(app, ["agent", "delete", "a1", "--yes"])
        assert result.exit_code == 0
        mock_del.assert_called_once_with("/api/v1/agents/a1")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.agents.api_delete")
    def test_delete_agent_aborts_without_confirm(self, mock_del, _):
        result = runner.invoke(app, ["agent", "delete", "a1"], input="n\n")
        assert result.exit_code != 0  # aborted
        mock_del.assert_not_called()


# ── App commands ───────────────────────────────────────────────


class TestAppCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.apps.api_get")
    def test_list_apps(self, mock_get, _):
        mock_get.return_value = {
            "items": [{
                "id": "p" * 36, "name": "Viewer", "app_type": "visualization",
                "runtime_status": "active", "created_at": "2026-01-01T00:00:00",
            }],
            "total": 1,
        }
        result = runner.invoke(app, ["app", "list"])
        assert result.exit_code == 0
        assert "Viewer" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.apps.api_post")
    def test_deploy_app(self, mock_post, _):
        mock_post.return_value = {"id": "app1", "runtime_status": "deploying"}
        result = runner.invoke(app, ["app", "deploy", "app1"])
        assert result.exit_code == 0
        mock_post.assert_called_once_with("/api/v1/apps/app1/deploy")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.apps.api_post")
    def test_stop_app(self, mock_post, _):
        mock_post.return_value = {"id": "app1", "runtime_status": "stopped"}
        result = runner.invoke(app, ["app", "stop", "app1"])
        assert result.exit_code == 0
        mock_post.assert_called_once_with("/api/v1/apps/app1/stop")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.apps.api_delete")
    def test_delete_app(self, mock_del, _):
        result = runner.invoke(app, ["app", "delete", "app1", "--yes"])
        assert result.exit_code == 0
        mock_del.assert_called_once_with("/api/v1/apps/app1")


# ── Task-run commands ──────────────────────────────────────────


class TestTaskRunCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.task_runs.api_get")
    def test_list_task_runs(self, mock_get, _):
        mock_get.return_value = {
            "items": [{
                "id": "t" * 36, "tool_name": "Hit Triage", "status": "pending",
                "assigned_user_email": "a@b.com", "created_at": "2026-01-01T00:00:00",
            }],
            "total": 1,
        }
        result = runner.invoke(app, ["task-run", "list"])
        assert result.exit_code == 0
        assert "pending" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.task_runs.api_post")
    def test_accept_task_run(self, mock_post, _):
        mock_post.return_value = {"id": "tr1", "status": "accepted"}
        result = runner.invoke(app, ["task-run", "accept", "tr1"])
        assert result.exit_code == 0
        mock_post.assert_called_once_with("/api/v1/task-runs/tr1/accept")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.task_runs.api_post")
    def test_cancel_task_run(self, mock_post, _):
        mock_post.return_value = {"id": "tr1", "status": "cancelled"}
        result = runner.invoke(app, ["task-run", "cancel", "tr1"])
        assert result.exit_code == 0
        mock_post.assert_called_once_with("/api/v1/task-runs/tr1/cancel")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.task_runs.api_delete")
    def test_delete_task_run(self, mock_del, _):
        result = runner.invoke(app, ["task-run", "delete", "tr1", "--yes"])
        assert result.exit_code == 0
        mock_del.assert_called_once_with("/api/v1/task-runs/tr1")


# ── Tool-run commands ──────────────────────────────────────────


class TestToolRunCommands:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.tool_runs.api_get")
    def test_list_tool_runs(self, mock_get, _):
        mock_get.return_value = {
            "items": [{
                "id": "r" * 36, "tool_name": "Docking", "status": "completed",
                "created_at": "2026-01-01T00:00:00",
                "started_at": "2026-01-01T00:01:00", "finished_at": "2026-01-01T00:05:00",
            }],
            "total": 1,
        }
        result = runner.invoke(app, ["tool-run", "list"])
        assert result.exit_code == 0
        assert "completed" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.tool_runs.api_get")
    def test_get_tool_run(self, mock_get, _):
        mock_get.return_value = {
            "id": "r1", "tool_name": "Docking", "status": "completed", "artifacts": [],
        }
        result = runner.invoke(app, ["tool-run", "get", "r1"])
        assert result.exit_code == 0
        mock_get.assert_called_with("/api/v1/tool-runs/r1")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.tool_runs.api_post")
    def test_cancel_tool_run(self, mock_post, _):
        mock_post.return_value = {"id": "r1", "status": "cancelled"}
        result = runner.invoke(app, ["tool-run", "cancel", "r1"])
        assert result.exit_code == 0
        mock_post.assert_called_once_with("/api/v1/tool-runs/r1/cancel")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.tool_runs.api_post")
    def test_restart_tool_run(self, mock_post, _):
        mock_post.return_value = {"id": "r2", "status": "pending", "restarted_from": "r1"}
        result = runner.invoke(app, ["tool-run", "restart", "r1"])
        assert result.exit_code == 0
        mock_post.assert_called_once_with("/api/v1/tool-runs/r1/restart")


# ── Tool-run helpers ───────────────────────────────────────────


class TestToolRunHelpers:
    def test_load_params_inline_json(self):
        from cli.commands.tool_runs import _load_params

        assert _load_params('{"a": 1}') == {"a": 1}

    def test_load_params_empty_object(self):
        from cli.commands.tool_runs import _load_params

        assert _load_params("{}") == {}

    def test_load_params_from_file(self, tmp_path):
        from cli.commands.tool_runs import _load_params

        f = tmp_path / "p.json"
        f.write_text('{"receptor": "x.pdbqt"}')
        assert _load_params(f"@{f}") == {"receptor": "x.pdbqt"}

    def test_load_params_invalid_json_exits(self):
        from cli.commands.tool_runs import _load_params

        with pytest.raises(typer.Exit):
            _load_params("{not json}")

    @patch("cli.commands.tool_runs.api_get")
    def test_resolve_tool_id_by_slug(self, mock_get):
        from cli.commands.tool_runs import _resolve_tool_id

        mock_get.return_value = {"id": "tool-123"}
        assert _resolve_tool_id("docking") == "tool-123"


# ── App / task-run: get, empty, error branches ─────────────────


class TestAppTaskRunBranches:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.apps.api_get")
    def test_get_app(self, mock_get, _):
        mock_get.return_value = {"id": "app1", "name": "Viewer", "slug": "viewer"}
        result = runner.invoke(app, ["app", "get", "viewer"])
        assert result.exit_code == 0
        mock_get.assert_called_with("/api/v1/apps/viewer")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.apps.api_get")
    def test_list_apps_empty(self, mock_get, _):
        mock_get.return_value = {"items": [], "total": 0}
        result = runner.invoke(app, ["app", "list"])
        assert result.exit_code == 0
        assert "No apps found." in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.apps.api_post", side_effect=ApiError(409, "already deploying"))
    def test_deploy_app_error(self, mock_post, _):
        result = runner.invoke(app, ["app", "deploy", "app1"])
        assert result.exit_code == 1
        assert "already deploying" in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.task_runs.api_get")
    def test_get_task_run(self, mock_get, _):
        mock_get.return_value = {"id": "tr1", "status": "pending"}
        result = runner.invoke(app, ["task-run", "get", "tr1"])
        assert result.exit_code == 0
        mock_get.assert_called_with("/api/v1/task-runs/tr1")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.task_runs.api_get")
    def test_list_task_runs_empty(self, mock_get, _):
        mock_get.return_value = {"items": [], "total": 0}
        result = runner.invoke(app, ["task-run", "list"])
        assert result.exit_code == 0
        assert "No task runs found." in result.output

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.task_runs.api_post", side_effect=ApiError(409, "not assignable"))
    def test_accept_task_run_error(self, mock_post, _):
        result = runner.invoke(app, ["task-run", "accept", "tr1"])
        assert result.exit_code == 1
        assert "not assignable" in result.output


# ── Dataset: get + versions ────────────────────────────────────


class TestDatasetGetVersions:
    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.datasets.api_get")
    def test_get_dataset(self, mock_get, _):
        mock_get.return_value = {"id": "d1", "name": "ChEMBL", "slug": "chembl"}
        result = runner.invoke(app, ["dataset", "get", "chembl"])
        assert result.exit_code == 0
        mock_get.assert_called_with("/api/v1/datasets/chembl")

    @patch("cli.client.load_tokens", return_value={"access_token": "tok"})
    @patch("cli.commands.datasets.api_get", side_effect=ApiError(404, "no such dataset"))
    def test_get_dataset_not_found(self, mock_get, _):
        result = runner.invoke(app, ["dataset", "get", "nope"])
        assert result.exit_code == 1
        assert "no such dataset" in result.output
