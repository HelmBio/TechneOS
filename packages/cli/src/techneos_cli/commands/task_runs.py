"""Task-run commands — list, get, accept, cancel, delete (human tasks)."""
from __future__ import annotations

from typing import Any

import typer

from techneos_cli.client import ApiError, api_delete, api_get, api_post, require_auth
from techneos_cli.output import print_detail, print_error, print_success, print_table

task_run_app = typer.Typer(name="task-run", help="Task-run management.", no_args_is_help=True)


@task_run_app.command("list")
def list_task_runs(
    status: str = typer.Option("", "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List human task runs."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if status:
        params["status"] = status
    try:
        data = api_get("/api/v1/task-runs", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No task runs found.")
            return
        print_table(
            columns=["ID", "Tool", "Version", "Status", "Outcome", "Started"],
            rows=[
                [
                    t["id"],
                    t.get("tool_slug", "—"),
                    str(t.get("tool_version_num") or "—"),
                    t.get("status", "—"),
                    t.get("outcome") or "—",
                    (t.get("started_at") or "")[:19] or "—",
                ]
                for t in items
            ],
            title=f"Task runs ({data['total']} total)",
            fold={"Tool"},
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@task_run_app.command("get")
def get_task_run(task_run_id: str = typer.Argument(..., help="Task-run ID")) -> None:
    """Get task-run details."""
    require_auth()
    try:
        data = api_get(f"/api/v1/task-runs/{task_run_id}")
        print_detail(data, title="Task run")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@task_run_app.command("accept")
def accept_task_run(task_run_id: str = typer.Argument(..., help="Task-run ID")) -> None:
    """Accept a task run (take ownership of the assignment)."""
    require_auth()
    try:
        data = api_post(f"/api/v1/task-runs/{task_run_id}/accept")
        print_success(f"Accepted task run {task_run_id}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@task_run_app.command("cancel")
def cancel_task_run(task_run_id: str = typer.Argument(..., help="Task-run ID")) -> None:
    """Cancel a task run."""
    require_auth()
    try:
        data = api_post(f"/api/v1/task-runs/{task_run_id}/cancel")
        print_success(f"Cancelled task run {task_run_id}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@task_run_app.command("delete")
def delete_task_run(
    task_run_id: str = typer.Argument(..., help="Task-run ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a task run."""
    require_auth()
    if not yes:
        typer.confirm(f"Delete task run {task_run_id}?", abort=True)
    try:
        api_delete(f"/api/v1/task-runs/{task_run_id}")
        print_success(f"Deleted task run {task_run_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
