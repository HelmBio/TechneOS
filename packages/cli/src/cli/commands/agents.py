"""Agent commands — list, get, delete."""
from __future__ import annotations

from typing import Any

import typer

from cli.client import ApiError, api_delete, api_get, require_auth
from cli.output import print_detail, print_error, print_success, print_table

agent_app = typer.Typer(name="agent", help="Agent management.", no_args_is_help=True)


@agent_app.command("list")
def list_agents(
    q: str = typer.Option("", "--query", "-q", help="Search query"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List agents."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if q:
        params["q"] = q
    try:
        data = api_get("/api/v1/agents", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No agents found.")
            return
        print_table(
            columns=["ID", "Name", "Type", "Public", "Created"],
            rows=[
                [
                    a["id"][:12] + "…",
                    a["name"],
                    a.get("agent_type", "—"),
                    "yes" if a.get("is_public") else "no",
                    a["created_at"][:19],
                ]
                for a in items
            ],
            title=f"Agents ({data['total']} total)",
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@agent_app.command("get")
def get_agent(identifier: str = typer.Argument(..., help="Agent ID or slug")) -> None:
    """Get agent details."""
    require_auth()
    try:
        data = api_get(f"/api/v1/agents/{identifier}")
        print_detail(data, title="Agent")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@agent_app.command("delete")
def delete_agent(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete an agent."""
    require_auth()
    if not yes:
        typer.confirm(f"Delete agent {agent_id}?", abort=True)
    try:
        api_delete(f"/api/v1/agents/{agent_id}")
        print_success(f"Deleted agent {agent_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
