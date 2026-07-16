"""App commands — list, get, deploy, stop, delete."""
from __future__ import annotations

from typing import Any

import typer

from techneos_cli.client import ApiError, api_delete, api_get, api_post, require_auth
from techneos_cli.output import print_detail, print_error, print_success, print_table

app_app = typer.Typer(name="app", help="App management.", no_args_is_help=True)


@app_app.command("list")
def list_apps(
    q: str = typer.Option("", "--query", "-q", help="Search query"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List embedded apps."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if q:
        params["q"] = q
    try:
        data = api_get("/api/v1/apps", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No apps found.")
            return
        print_table(
            columns=["ID", "Slug", "Name", "Category", "Launch Mode", "Status", "Created"],
            rows=[
                [
                    a["id"],
                    a.get("slug", "—"),
                    a["name"],
                    a.get("category", "—"),
                    a.get("launch_mode", "—"),
                    a.get("status", "—"),
                    a["created_at"][:19],
                ]
                for a in items
            ],
            title=f"Apps ({data['total']} total)",
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@app_app.command("get")
def get_app(identifier: str = typer.Argument(..., help="App ID or slug")) -> None:
    """Get app details."""
    require_auth()
    try:
        data = api_get(f"/api/v1/apps/{identifier}")
        print_detail(data, title="App")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@app_app.command("deploy")
def deploy_app(app_id: str = typer.Argument(..., help="App ID")) -> None:
    """Deploy an app (build/start its container)."""
    require_auth()
    try:
        data = api_post(f"/api/v1/apps/{app_id}/deploy")
        print_success(f"Deploying app {app_id}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@app_app.command("stop")
def stop_app(app_id: str = typer.Argument(..., help="App ID")) -> None:
    """Stop a running app."""
    require_auth()
    try:
        data = api_post(f"/api/v1/apps/{app_id}/stop")
        print_success(f"Stopped app {app_id}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@app_app.command("delete")
def delete_app(
    app_id: str = typer.Argument(..., help="App ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an app."""
    require_auth()
    if not yes:
        typer.confirm(f"Delete app {app_id}?", abort=True)
    try:
        api_delete(f"/api/v1/apps/{app_id}")
        print_success(f"Deleted app {app_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
