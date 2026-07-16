"""Config commands — show and set which platform the CLI talks to."""

from __future__ import annotations

import typer

from techneos_cli.config import (
    CONFIG_FILE,
    get_base_url,
    get_saved_base_url,
    load_tokens,
    set_base_url,
)
from techneos_cli.output import print_detail, print_success

config_app = typer.Typer(name="config", help="CLI configuration.", no_args_is_help=True)


@config_app.command("show")
def show() -> None:
    """Show which platform this CLI talks to, and whether you're logged in."""
    # Naming the config file without saying whether it exists invites a hunt
    # for a file that was never written: the URL below is a built-in fallback
    # until something saves one.
    saved = get_saved_base_url()
    print_detail(
        {
            "base_url": get_base_url(),
            "base_url_source": "config file" if saved else "built-in default",
            "config_file": str(CONFIG_FILE),
            "config_file_exists": CONFIG_FILE.exists(),
            "logged_in": bool(load_tokens()),
        },
    )


@config_app.command("set-url")
def set_url(url: str = typer.Argument(..., help="Platform URL, e.g. https://techneos.example.com")) -> None:
    """Point the CLI at a platform, without logging in.

    Existing tokens are left alone: they belong to whichever platform issued
    them, so they simply won't be accepted by a different one.
    """
    set_base_url(url)
    print_success(f"Platform URL set to {get_base_url()}")
