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

# Enough of a UUID to recognise a row by, and to match against a full id.
_ID_DISPLAY_WIDTH = 13


def set_json_mode(enabled: bool) -> None:
    """Enable/disable JSON output mode."""
    global _json_mode
    _json_mode = enabled


def is_json_mode() -> bool:
    return _json_mode


def print_json(data: Any) -> None:
    """Pretty-print JSON to stdout."""
    typer.echo(json.dumps(data, indent=2, default=str))


def print_table(
    columns: list[str],
    rows: list[list[str]],
    title: str | None = None,
    fold: set[str] | None = None,
) -> None:
    """Print a rich table, or JSON if --json mode is on.

    `fold` names columns holding an identifier a user retypes elsewhere. Those
    wrap instead of clipping: a slug has no spaces, so the table would elide it
    to a prefix that still looks like a slug — worse than a wrapped one, since
    the whole point of showing it is that it can be copied. A column named
    "Slug" is always folded; name any other identifier column here.

    Pass ids in full. An "ID" column is shortened here, at render time, so the
    abbreviation stays a property of the terminal: JSON mode emits what it was
    given, and a caller that trims beforehand would put an unusable id there.
    """
    if _json_mode:
        # In JSON mode, output as list of dicts
        out = [{col: val for col, val in zip(columns, row, strict=False)} for row in rows]
        print_json(out)
        return

    fold_cols = {c.lower() for c in (fold or set())} | {"slug"}
    table = Table(title=title, show_lines=False)
    for col in columns:
        name = col.lower()
        if name in fold_cols:
            table.add_column(col, overflow="fold")
        elif name == "id":
            table.add_column(col, no_wrap=True, max_width=_ID_DISPLAY_WIDTH)
        else:
            table.add_column(col)
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
