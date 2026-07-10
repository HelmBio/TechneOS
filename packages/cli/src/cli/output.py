"""Output formatting helpers — tables, JSON, status."""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

# Global output format (set by --json flag on root app)
_json_mode = False


def set_json_mode(enabled: bool) -> None:
    """Enable/disable JSON output mode."""
    global _json_mode
    _json_mode = enabled


def is_json_mode() -> bool:
    return _json_mode


def print_json(data: Any) -> None:
    """Pretty-print JSON to stdout."""
    typer.echo(json.dumps(data, indent=2, default=str))


def print_table(columns: list[str], rows: list[list[str]], title: str | None = None) -> None:
    """Print a rich table, or JSON if --json mode is on."""
    if _json_mode:
        # In JSON mode, output as list of dicts
        out = [{col: val for col, val in zip(columns, row, strict=False)} for row in rows]
        print_json(out)
        return

    table = Table(title=title, show_lines=False)
    for col in columns:
        table.add_column(col, no_wrap=(col.lower() == "id"))
    for row in rows:
        table.add_row(*row)
    console.print(table)


def print_detail(data: dict[str, Any], title: str | None = None) -> None:
    """Print a single record as key-value pairs, or JSON."""
    if _json_mode:
        print_json(data)
        return

    if title:
        console.print(f"[bold]{title}[/bold]")
    for key, value in data.items():
        console.print(f"  [cyan]{key}:[/cyan] {value}")


def print_success(msg: str) -> None:
    if _json_mode:
        print_json({"status": "ok", "message": msg})
    else:
        console.print(f"[green]{msg}[/green]")


def print_error(msg: str) -> None:
    err_console.print(f"[red]Error:[/red] {msg}")
