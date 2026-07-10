"""HTTP client wrapper with automatic auth header injection and token refresh."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import typer

from cli.config import get_base_url, load_tokens, save_tokens

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Raised when the API returns a non-2xx status."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


def _auth_headers() -> dict[str, str]:
    """Build Authorization header from stored token."""
    tokens = load_tokens()
    if tokens and tokens.get("access_token"):
        return {"Authorization": f"Bearer {tokens['access_token']}"}
    return {}


def _try_refresh() -> bool:
    """Attempt to refresh the access token using the stored refresh token.

    Returns True if refresh succeeded and new tokens were saved.
    """
    tokens = load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        return False

    base_url = get_base_url()
    refresh_token = tokens["refresh_token"]
    try:
        resp = httpx.post(
            f"{base_url}/api/v1/auth/refresh",
            params={"refresh_token": refresh_token},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return False
        body = resp.json()
        save_tokens(body["access_token"], body["refresh_token"])
        return True
    except Exception:
        return False


def _handle_response(resp: httpx.Response) -> httpx.Response:
    """Check response status and raise ApiError on failure."""
    if resp.status_code == 401:
        raise ApiError(401, "Unauthorized — run `techneos auth login` first")
    if resp.status_code == 403:
        raise ApiError(403, "Forbidden — insufficient permissions")
    if resp.status_code == 404:
        detail = _extract_detail(resp, "Not found")
        raise ApiError(404, detail)
    if resp.status_code == 409:
        detail = _extract_detail(resp, "Conflict")
        raise ApiError(409, detail)
    if resp.status_code == 422:
        detail = _extract_detail(resp, "Validation error")
        raise ApiError(422, detail)
    if resp.status_code >= 400:
        detail = _extract_detail(resp, resp.text[:200])
        raise ApiError(resp.status_code, detail)
    return resp


def _extract_detail(resp: httpx.Response, default: str) -> str:
    """Try to extract 'detail' from a JSON error response."""
    import contextlib

    with contextlib.suppress(Exception):
        body = resp.json()
        return str(body.get("detail", default))
    return default


def get_client(base_url: str | None = None, timeout: float = 30.0) -> httpx.Client:
    """Create a configured httpx.Client with auth headers."""
    url = base_url or get_base_url()
    return httpx.Client(
        base_url=url,
        headers=_auth_headers(),
        timeout=timeout,
    )


def _request_with_retry(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    files: Any | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """Execute an HTTP request with automatic 401 → refresh → retry.

    If the first request returns 401 and a refresh token is available,
    attempts to refresh the access token and retries exactly once.
    """
    with get_client(timeout=timeout) as c:
        kwargs: dict[str, Any] = {}
        if json is not None:
            kwargs["json"] = json
        if params is not None:
            kwargs["params"] = params
        if files is not None:
            kwargs["files"] = files

        resp = c.request(method, path, **kwargs)

        if resp.status_code == 401 and _try_refresh():
            # Retry with refreshed token
            new_headers = _auth_headers()
            c.headers.update(new_headers)
            resp = c.request(method, path, **kwargs)

    return resp


def api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET request to the platform API. Returns parsed JSON."""
    resp = _handle_response(_request_with_retry("GET", path, params=params))
    return resp.json() if resp.text else None


def api_post(path: str, json: dict[str, Any] | None = None) -> Any:
    """POST request to the platform API. Returns parsed JSON."""
    resp = _handle_response(_request_with_retry("POST", path, json=json))
    return resp.json() if resp.text else None


def api_patch(path: str, json: dict[str, Any] | None = None) -> Any:
    """PATCH request to the platform API. Returns parsed JSON."""
    resp = _handle_response(_request_with_retry("PATCH", path, json=json))
    return resp.json() if resp.text else None


def api_delete(path: str) -> None:
    """DELETE request to the platform API."""
    _handle_response(_request_with_retry("DELETE", path))


def api_upload(path: str, file_path: str, params: dict[str, Any] | None = None) -> Any:
    """Upload a file via multipart POST."""
    import os

    fname = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        resp = _handle_response(
            _request_with_retry(
                "POST", path, files={"file": (fname, f)}, params=params, timeout=300.0
            )
        )
        return resp.json() if resp.text else None


def api_download(url: str, dest: str) -> str:
    """Download from a (presigned) URL to a local file. Returns dest path."""
    with httpx.Client(timeout=300.0, follow_redirects=True) as c, c.stream("GET", url) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=8192):
                f.write(chunk)
    return dest


def require_auth() -> None:
    """Exit with error if user is not logged in."""
    tokens = load_tokens()
    if not tokens or not tokens.get("access_token"):
        typer.echo("Not logged in. Run `techneos auth login` first.", err=True)
        raise typer.Exit(1)
