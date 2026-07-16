"""CLI configuration — platform URL, token storage path, output format."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

# Default config directory: ~/.techneos/
CONFIG_DIR = Path.home() / ".techneos"
TOKEN_FILE = CONFIG_DIR / "token.json"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_BASE_URL = "http://localhost:8000"


def ensure_config_dir() -> None:
    """Create the config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_saved_base_url() -> str | None:
    """The platform URL explicitly saved to config, or None if never set.

    `get_base_url` can't tell a saved value from the fallback, which is the
    one distinction someone asking where their CLI points actually needs.
    """
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        # A corrupt config shouldn't take every command down with it; the
        # default below still works, and `config show` reports the fallback.
        return None
    url = data.get("base_url")
    return str(url) if url else None


def get_base_url() -> str:
    """Read the platform base URL from config, or return the default."""
    return get_saved_base_url() or DEFAULT_BASE_URL


def set_base_url(url: str) -> None:
    """Persist the platform base URL to config."""
    ensure_config_dir()
    data: dict[str, Any] = {}
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
    data["base_url"] = url.rstrip("/")
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def save_tokens(access_token: str, refresh_token: str) -> None:
    """Persist tokens to disk."""
    ensure_config_dir()
    TOKEN_FILE.write_text(
        json.dumps(
            {"access_token": access_token, "refresh_token": refresh_token},
            indent=2,
        )
    )
    TOKEN_FILE.chmod(0o600)


def load_tokens() -> dict[str, Any] | None:
    """Load tokens from disk, or return None if not logged in."""
    if not TOKEN_FILE.exists():
        return None
    try:
        return cast(dict[Any, Any] | None, json.loads(TOKEN_FILE.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def clear_tokens() -> None:
    """Delete stored tokens (logout)."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
