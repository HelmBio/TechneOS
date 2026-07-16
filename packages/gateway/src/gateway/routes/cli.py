"""Serves the techneos-cli wheel to customers.

The CLI is distributed by the deployment it talks to, not from a public index,
so a client is version-matched to its platform at install time and air-gapped
sites need no outbound access. Exposed as a PEP 503 "simple" index rather than
a bare download URL because pip derives a wheel's filename from the URL it is
given — it does not read Content-Disposition and does not re-read the filename
after a redirect. An index is therefore the only shape that yields a stable,
version-free install command.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from core.config import get_settings
from gateway.client_version import PLATFORM_VERSION

router = APIRouter()

# PEP 503 normalized name. The wheel file itself uses the underscored form.
PROJECT_NAME = "techneos-cli"

# Where lookups for anything other than techneos-cli are sent.
UPSTREAM_INDEX = "https://pypi.org/simple"


def _normalize(project: str) -> str:
    """PEP 503 name normalization."""
    return re.sub(r"[-_.]+", "-", project).lower()


def _wheel_dir() -> Path:
    return Path(get_settings().cli_wheel_dir)


def _wheels() -> list[Path]:
    """Every CLI wheel available to serve, newest filename last.

    Also the allowlist for downloads: only a file enumerated here can be
    fetched, so a crafted filename cannot escape the directory.
    """
    directory = _wheel_dir()
    if not directory.is_dir():
        return []
    return sorted(directory.glob("techneos_cli-*.whl"))


def _no_wheel() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=(
            f"No techneos-cli wheel is available from this deployment "
            f"(looked in '{_wheel_dir()}'). Build one with `make build-cli-wheel`."
        ),
    )


@router.get("/cli/version")
async def version() -> dict[str, str]:
    """Report the techneos-cli version this deployment serves.

    Install it with pip, uv or pipx, pointing at `index_url` — the index also
    resolves the client's dependencies, so it needs no second index:

        pipx install --index-url <this-host>/cli/simple/ techneos-cli

    The index pages and the wheel itself are deliberately absent from this
    schema: they are consumed by a package installer, not called directly.
    """
    wheels = _wheels()
    if not wheels:
        raise _no_wheel()
    return {
        "platform_version": PLATFORM_VERSION,
        "cli_version": _version_of(wheels[-1]),
        "wheel": wheels[-1].name,
        "index_url": "/cli/simple/",
    }


def _version_of(wheel: Path) -> str:
    """Pull the version out of a wheel filename (name-version-...-any.whl)."""
    parts = wheel.name.split("-")
    return parts[1] if len(parts) > 1 else "unknown"


@router.get("/cli/simple/", include_in_schema=False)
async def simple_index() -> HTMLResponse:
    """PEP 503 root index — lists the projects this index serves."""
    return HTMLResponse(
        "<!DOCTYPE html><html><body>\n"
        f'<a href="/cli/simple/{PROJECT_NAME}/">{PROJECT_NAME}</a><br/>\n'
        "</body></html>\n"
    )


@router.get("/cli/simple/{project}/", include_in_schema=False)
async def simple_project(project: str) -> Response:
    """PEP 503 project page — links to each downloadable wheel.

    Anything that isn't techneos-cli is forwarded upstream, so this can be a
    client's sole ``--index-url``: pip resolves the CLI's own dependencies
    (typer, httpx, rich) through here without a second index. That matters for
    more than convenience — pip merges multiple indexes and takes the highest
    version it finds across all of them, so telling customers to add PyPI as an
    extra index would let anyone who registers the (currently unclaimed)
    techneos-cli name there outrank the client we serve.
    """
    normalized = _normalize(project)
    if normalized != PROJECT_NAME:
        return RedirectResponse(f"{UPSTREAM_INDEX}/{normalized}/", status_code=302)

    wheels = _wheels()
    if not wheels:
        raise _no_wheel()

    links = "\n".join(
        f'<a href="/cli/dist/{html.escape(w.name)}">{html.escape(w.name)}</a><br/>' for w in wheels
    )
    return HTMLResponse(f"<!DOCTYPE html><html><body>\n{links}\n</body></html>\n")


@router.get("/cli/dist/{filename}", include_in_schema=False)
async def download_wheel(filename: str) -> FileResponse:
    """Serve a wheel by name, restricted to the files the index lists."""
    for wheel in _wheels():
        if wheel.name == filename:
            return FileResponse(
                wheel,
                media_type="application/octet-stream",
                filename=wheel.name,
            )
    raise HTTPException(status_code=404, detail=f"No such CLI wheel: {filename}")
