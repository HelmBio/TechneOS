"""CLI client for TechneOS."""

from __future__ import annotations

import typer

from cli.commands.agents import agent_app
from cli.commands.apps import app_app
from cli.commands.auth import auth_app
from cli.commands.datasets import dataset_app
from cli.commands.pipelines import pipeline_app, run_app
from cli.commands.task_runs import task_run_app
from cli.commands.tool_runs import tool_run_app
from cli.commands.tools import tool_app

app = typer.Typer(
    name="techneos",
    help="TechneOS CLI",
    no_args_is_help=True,
)

# Register command groups
app.add_typer(auth_app)
app.add_typer(dataset_app)
app.add_typer(tool_app)
app.add_typer(tool_run_app)
app.add_typer(pipeline_app)
app.add_typer(run_app)
app.add_typer(agent_app)
app.add_typer(app_app)
app.add_typer(task_run_app)


@app.callback()
def main(
    json_output: bool | None = typer.Option(None, "--json", help="Output in JSON format"),
) -> None:
    """TechneOS CLI — manage datasets, tools, pipelines, and runs."""
    if json_output:
        from cli.output import set_json_mode

        set_json_mode(True)


@app.command()
def version() -> None:
    """Show the CLI version."""
    typer.echo("techneos-cli v0.1.0")


@app.command()
def health(url: str = typer.Option("", help="Platform URL (uses saved config if empty)")) -> None:
    """Check platform health."""
    import httpx

    from cli.config import get_base_url

    target = url or get_base_url()
    try:
        resp = httpx.get(f"{target}/health", timeout=5.0)
        typer.echo(resp.json())
    except httpx.ConnectError:
        typer.echo(f"Cannot connect to {target}", err=True)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
