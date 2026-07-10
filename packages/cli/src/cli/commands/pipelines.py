"""Pipeline commands — list, get, create, submit, status, cancel."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from cli.client import ApiError, api_delete, api_get, api_post, require_auth
from cli.output import print_detail, print_error, print_success, print_table

pipeline_app = typer.Typer(name="pipeline", help="Pipeline management.", no_args_is_help=True)


@pipeline_app.command("list")
def list_pipelines(
    q: str = typer.Option("", "--query", "-q", help="Search query"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List pipeline definitions."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if q:
        params["q"] = q

    try:
        data = api_get("/api/v1/pipelines", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No pipelines found.")
            return
        print_table(
            columns=["ID", "Name", "Version", "Steps", "Public", "Created"],
            rows=[
                [
                    p["id"][:12] + "…",
                    p["name"],
                    str(p.get("version", "—")),
                    str(len(p.get("steps", []))),
                    "yes" if p.get("is_public") else "no",
                    p["created_at"][:19],
                ]
                for p in items
            ],
            title=f"Pipelines ({data['total']} total)",
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@pipeline_app.command("get")
def get_pipeline(pipeline_id: str = typer.Argument(..., help="Pipeline ID")) -> None:
    """Get pipeline definition details."""
    require_auth()
    try:
        data = api_get(f"/api/v1/pipelines/{pipeline_id}")
        print_detail(data, title="Pipeline")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@pipeline_app.command("create")
def create_pipeline(
    file: Path = typer.Argument(..., help="Pipeline definition JSON file", exists=True),
) -> None:
    """Create a pipeline from a JSON definition file.

    The file should contain: name, slug, steps, and optionally
    edges, default_parameters, parameters_schema, tags, is_public.
    """
    require_auth()
    try:
        body = json.loads(file.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print_error(f"Failed to read pipeline file: {exc}")
        raise typer.Exit(1) from None

    try:
        data = api_post("/api/v1/pipelines", json=body)
        print_success(f"Created pipeline {data['id']}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@pipeline_app.command("delete")
def delete_pipeline(
    pipeline_id: str = typer.Argument(..., help="Pipeline ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a pipeline and all its runs."""
    require_auth()
    if not yes:
        typer.confirm(f"Delete pipeline {pipeline_id}?", abort=True)
    try:
        api_delete(f"/api/v1/pipelines/{pipeline_id}")
        print_success(f"Deleted pipeline {pipeline_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


# ── Run sub-commands ──────────────────────────────────────────

run_app = typer.Typer(name="pipeline-run", help="Pipeline-run management.", no_args_is_help=True)


@run_app.command("submit")
def submit_run(
    pipeline_id: str = typer.Argument(..., help="Pipeline definition ID"),
    params_json: str = typer.Option("{}", "--params", "-p", help="Run parameters as JSON string"),
) -> None:
    """Submit a new pipeline run."""
    require_auth()
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as exc:
        print_error(f"Invalid JSON for --params: {exc}")
        raise typer.Exit(1) from None

    try:
        data = api_post(
            "/api/v1/pipeline-runs",
            json={"pipeline_id": pipeline_id, "parameters": params},
        )
        print_success(f"Submitted run {data['id']}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@run_app.command("list")
def list_runs(
    pipeline_id: str = typer.Option("", "--pipeline", "-p", help="Filter by pipeline ID"),
    run_status: str = typer.Option("", "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List pipeline runs."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if pipeline_id:
        params["pipeline_id"] = pipeline_id
    if run_status:
        params["status"] = run_status

    try:
        data = api_get("/api/v1/pipeline-runs", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No runs found.")
            return
        print_table(
            columns=["ID", "Pipeline", "Status", "Submitted", "Started", "Finished"],
            rows=[
                [
                    r["id"][:12] + "…",
                    r["pipeline_id"][:12] + "…",
                    r["status"],
                    r["created_at"][:19],
                    (r.get("started_at") or "—")[:19],
                    (r.get("finished_at") or "—")[:19],
                ]
                for r in items
            ],
            title=f"Runs ({data['total']} total)",
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@run_app.command("get")
def get_run(run_id: str = typer.Argument(..., help="Run ID")) -> None:
    """Get run details with steps and artifacts."""
    require_auth()
    try:
        data = api_get(f"/api/v1/pipeline-runs/{run_id}")
        steps = data.pop("steps", [])
        artifacts = data.pop("artifacts", [])
        print_detail(data, title="Run")

        if steps:
            typer.echo("")
            print_table(
                columns=["Step", "Status", "Started", "Finished"],
                rows=[
                    [
                        s["step_name"],
                        s["status"],
                        (s.get("started_at") or "—")[:19],
                        (s.get("finished_at") or "—")[:19],
                    ]
                    for s in steps
                ],
                title="Steps",
            )

        if artifacts:
            typer.echo("")
            print_table(
                columns=["ID", "Name", "Type", "File", "Size"],
                rows=[
                    [
                        a["id"][:12] + "…",
                        a["name"],
                        a.get("artifact_type", "—"),
                        a.get("file_name", "—"),
                        str(a.get("file_size", 0)),
                    ]
                    for a in artifacts
                ],
                title="Artifacts",
            )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@run_app.command("cancel")
def cancel_run(run_id: str = typer.Argument(..., help="Run ID")) -> None:
    """Cancel a pending or running pipeline run."""
    require_auth()
    try:
        data = api_post(f"/api/v1/pipeline-runs/{run_id}/cancel")
        print_success(f"Run {run_id} cancelled (status: {data['status']})")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
