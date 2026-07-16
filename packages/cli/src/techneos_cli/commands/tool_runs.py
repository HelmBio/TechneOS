"""Tool-run commands — submit, list, get, cancel, restart."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, cast

import httpx
import typer

from techneos_cli.client import (
    ApiError,
    _auth_headers,
    _handle_response,
    api_get,
    api_post,
    require_auth,
)
from techneos_cli.config import get_base_url
from techneos_cli.output import print_detail, print_error, print_success, print_table

tool_run_app = typer.Typer(
    name="tool-run",
    help="Tool-run management.",
    no_args_is_help=True,
)


# ── Submission ────────────────────────────────────────────────────────


@tool_run_app.command("submit")
def submit_tool_run(
    tool: str = typer.Argument(..., help="Tool ID or slug"),
    params: str = typer.Option(
        "{}", "--params", "-p", help="JSON parameters or @path/to/params.json"
    ),
    input_: list[str] = typer.Option(
        [],
        "--input",
        "-i",
        help="Bind an uploaded file to a parameter: parameter_name=@path/to/file (repeatable)",
    ),
    dataset: list[str] = typer.Option(
        [],
        "--dataset",
        "-d",
        help="Fill a dataset-ref parameter: parameter_name=slug:vN (repeatable)",
    ),
    version: int | None = typer.Option(
        None, "--version", "-v", help="Pin to a specific tool version"
    ),
    name: str = typer.Option("", "--name", help="Optional run name"),
    wait: bool = typer.Option(
        False, "--wait", "-w", help="Block until the run reaches a terminal state"
    ),
) -> None:
    """Submit a tool run.

    Examples:

        techneos tool-run submit admet-predictor --params '{"smiles":["CCO"]}'
        techneos tool-run submit admet-predictor --input dataset=@./mols.csv --wait
        techneos tool-run submit admet-predictor --dataset dataset=my-set:v1
    """
    require_auth()

    parameters = _load_params(params)

    for ds_arg in dataset:
        key, _, ref = ds_arg.partition("=")
        if not key or not ref:
            print_error(f"Invalid --dataset value '{ds_arg}' — expected name=ref")
            raise typer.Exit(1)
        parameters[key] = ref

    # Resolve the tool slug → id if needed (slugs are URL-friendly but the
    # submit endpoint takes the id).
    tool_id = _resolve_tool_id(tool)

    input_ids: list[str] = []
    for in_arg in input_:
        key, _, path = in_arg.partition("=")
        if not key or not path:
            print_error(f"Invalid --input value '{in_arg}' — expected name=@path")
            raise typer.Exit(1)
        file_path = path[1:] if path.startswith("@") else path
        if not os.path.exists(file_path):
            print_error(f"Input file not found: {file_path}")
            raise typer.Exit(1)
        input_id = _stage_input(key, file_path)
        input_ids.append(input_id)

    body: dict[str, Any] = {"tool_id": tool_id, "parameters": parameters, "input_ids": input_ids}
    if version is not None:
        # The API takes version_id, not the integer version number.
        body["version_id"] = _resolve_version_id(tool_id, version)
    if name:
        body["name"] = name

    try:
        data = api_post("/api/v1/tool-runs", json=body)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None

    print_success(f"Submitted tool run {data['id']}")
    print_detail(data)

    if wait:
        final = _wait_until_terminal(data["id"])
        _print_artifacts(final)


# ── Listing ───────────────────────────────────────────────────────────


@tool_run_app.command("list")
def list_tool_runs(
    tool: str = typer.Option("", "--tool", "-t", help="Filter by tool ID or slug"),
    run_status: str = typer.Option("", "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List tool runs."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if tool:
        params["tool_id"] = _resolve_tool_id(tool)
    if run_status:
        params["status"] = run_status

    try:
        data = api_get("/api/v1/tool-runs", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No tool runs found.")
            return
        print_table(
            columns=["ID", "Tool", "Version", "Status", "Submitted", "Started", "Finished"],
            rows=[
                [
                    r["id"],
                    r.get("tool_slug") or r.get("tool_id") or "—",
                    str(r.get("tool_version_num") or "—"),
                    r["status"],
                    r["created_at"][:19],
                    (r.get("started_at") or "—")[:19],
                    (r.get("finished_at") or "—")[:19],
                ]
                for r in items
            ],
            title=f"Tool Runs ({data['total']} total)",
            fold={"Tool"},
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@tool_run_app.command("get")
def get_tool_run(run_id: str = typer.Argument(..., help="Tool run ID")) -> None:
    """Get tool run details with artifacts."""
    require_auth()
    try:
        data = api_get(f"/api/v1/tool-runs/{run_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
    artifacts = data.pop("artifacts", [])
    inputs = data.pop("inputs", [])
    print_detail(data, title="Tool Run")

    if inputs:
        typer.echo("")
        print_table(
            columns=["Parameter", "File", "Size", "Status"],
            rows=[
                [i["parameter_name"], i["file_name"], str(i["file_size"]), i["status"]]
                for i in inputs
            ],
            title="Inputs",
        )

    if artifacts:
        typer.echo("")
        _print_artifact_table(artifacts)


@tool_run_app.command("cancel")
def cancel_tool_run(run_id: str = typer.Argument(..., help="Tool run ID")) -> None:
    """Cancel a running tool run."""
    require_auth()
    try:
        data = api_post(f"/api/v1/tool-runs/{run_id}/cancel")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
    print_success(f"Cancelled tool run {data['id']}")


@tool_run_app.command("restart")
def restart_tool_run(
    run_id: str = typer.Argument(..., help="Tool run ID"),
    wait: bool = typer.Option(False, "--wait", "-w"),
) -> None:
    """Restart a failed or cancelled tool run."""
    require_auth()
    try:
        data = api_post(f"/api/v1/tool-runs/{run_id}/restart")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
    print_success(f"Restarted as {data['id']}")
    if wait:
        final = _wait_until_terminal(data["id"])
        _print_artifacts(final)


# ── Helpers ───────────────────────────────────────────────────────────


def _load_params(value: str) -> dict[str, Any]:
    """Parse --params: either inline JSON or @path."""
    if value.startswith("@"):
        path = value[1:]
        try:
            return cast(dict[Any, Any], json.loads(Path(path).read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            print_error(f"Failed to read --params from {path}: {exc}")
            raise typer.Exit(1) from None
    try:
        return cast(dict[Any, Any], json.loads(value))
    except json.JSONDecodeError as exc:
        print_error(f"Invalid JSON for --params: {exc}")
        raise typer.Exit(1) from None


def _resolve_tool_id(tool_ref: str) -> str:
    """Return the tool's UUID. Accepts either a UUID or a slug."""
    # Cheap heuristic: a UUID-shaped string contains a hyphen at index 8.
    if "-" in tool_ref and len(tool_ref) >= 32:
        return tool_ref
    try:
        data = api_get(f"/api/v1/tools/by-slug/{tool_ref}")
        return cast(str, data["id"])
    except ApiError as e:
        print_error(f"Could not resolve tool '{tool_ref}': {e.detail}")
        raise typer.Exit(1) from None


def _resolve_version_id(tool_id: str, version: int) -> str:
    """Find a ToolVersion id given the tool id and integer version number."""
    try:
        data = api_get(f"/api/v1/tools/{tool_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
    for v in data.get("versions", []):
        if v.get("version") == version:
            return cast(str, v["id"])
    print_error(f"Tool {tool_id} has no version {version}")
    raise typer.Exit(1)


def _stage_input(parameter_name: str, file_path: str) -> str:
    """Upload a file to /tool-runs/inputs and return the input id."""
    base = get_base_url()
    fname = os.path.basename(file_path)
    with (
        open(file_path, "rb") as f,
        httpx.Client(base_url=base, headers=_auth_headers(), timeout=300.0) as c,
    ):
        resp = c.post(
            "/api/v1/tool-runs/inputs",
            files={"file": (fname, f)},
            data={"parameter_name": parameter_name},
        )
    try:
        _handle_response(resp)
    except ApiError as e:
        print_error(f"Upload failed for {file_path}: {e.detail}")
        raise typer.Exit(1) from None
    data = resp.json()
    typer.echo(f"  uploaded {fname} → input {data['id']}")
    return cast(str, data["id"])


def _wait_until_terminal(run_id: str, interval: float = 3.0, timeout: float = 3600.0) -> dict[str, Any]:
    """Poll until status is one of completed/failed/cancelled. Returns the final detail dict."""
    elapsed = 0.0
    last_status = ""
    while elapsed < timeout:
        try:
            data = api_get(f"/api/v1/tool-runs/{run_id}")
        except ApiError as e:
            print_error(e.detail)
            raise typer.Exit(1) from None
        status = data.get("status", "")
        if status != last_status:
            typer.echo(f"  [{status}]")
            last_status = status
        if status in ("completed", "failed", "cancelled"):
            return cast(dict[Any, Any], data)
        time.sleep(interval)
        elapsed += interval
    print_error("Timed out waiting for tool run")
    raise typer.Exit(2)


def _print_artifact_table(artifacts: list[dict[str, Any]]) -> None:
    """Render a run's artifacts. Fields match ToolRunArtifactResponse."""
    print_table(
        columns=["File", "Type", "Size", "ID"],
        rows=[
            [a["file_name"], a["io_type"], str(a["file_size"]), a["id"]] for a in artifacts
        ],
        title="Artifacts",
    )


def _print_artifacts(detail: dict[str, Any]) -> None:
    artifacts = detail.get("artifacts") or []
    if not artifacts:
        return
    _print_artifact_table(artifacts)
