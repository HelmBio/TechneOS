"""Tool commands — list, get, register."""
from __future__ import annotations

from typing import Any

import typer

from cli.client import ApiError, api_delete, api_get, api_post, require_auth
from cli.output import print_detail, print_error, print_success, print_table

tool_app = typer.Typer(name="tool", help="Tool management.", no_args_is_help=True)


@tool_app.command("list")
def list_tools(
    q: str = typer.Option("", "--query", "-q", help="Search query"),
    category: str = typer.Option("", "--category", "-c", help="Filter by category"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List registered tools."""
    require_auth()
    params: dict[str, Any] = {"skip": 0, "limit": limit}
    if q:
        params["q"] = q
    if category:
        params["category"] = category

    try:
        data = api_get("/api/v1/tools", params=params)
        items = data.get("items", [])
        if not items:
            typer.echo("No tools found.")
            return
        print_table(
            columns=["ID", "Name", "Category", "Public", "Created"],
            rows=[
                [
                    t["id"][:12] + "…",
                    t["name"],
                    t.get("category", "—"),
                    "yes" if t.get("is_public") else "no",
                    t["created_at"][:19],
                ]
                for t in items
            ],
            title=f"Tools ({data['total']} total)",
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@tool_app.command("get")
def get_tool(tool_id: str = typer.Argument(..., help="Tool ID")) -> None:
    """Get tool details with version history."""
    require_auth()
    try:
        data = api_get(f"/api/v1/tools/{tool_id}")
        versions = data.pop("versions", [])
        print_detail(data, title="Tool")
        if versions:
            typer.echo("")
            print_table(
                columns=["Version", "Docker Image", "Tag", "Status", "Created"],
                rows=[
                    [
                        str(v["version"]),
                        v.get("docker_image", "—"),
                        v.get("docker_tag", "—"),
                        v.get("status", "—"),
                        v["created_at"][:19],
                    ]
                    for v in versions
                ],
                title="Versions",
            )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@tool_app.command("register")
def register_tool(
    name: str = typer.Option(..., "--name", help="Tool name"),
    slug: str = typer.Option(..., "--slug", help="URL-friendly slug"),
    category: str = typer.Option("general", "--category", "-c", help="Category"),
    description: str = typer.Option("", "--desc", "-d", help="Description"),
    public: bool = typer.Option(False, "--public", help="Make publicly visible"),
) -> None:
    """Register a new tool."""
    require_auth()
    body: dict[str, Any] = {
        "name": name,
        "slug": slug,
        "category": category,
        "is_public": public,
    }
    if description:
        body["description"] = description

    try:
        data = api_post("/api/v1/tools", json=body)
        print_success(f"Registered tool {data['id']}")
        print_detail(data)
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@tool_app.command("delete")
def delete_tool(
    tool_id: str = typer.Argument(..., help="Tool ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a tool and all its versions."""
    require_auth()
    if not yes:
        typer.confirm(f"Delete tool {tool_id}?", abort=True)
    try:
        api_delete(f"/api/v1/tools/{tool_id}")
        print_success(f"Deleted tool {tool_id}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None
