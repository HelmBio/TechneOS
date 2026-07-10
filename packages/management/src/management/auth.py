from __future__ import annotations

import base64
import getpass
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from management.client import TechneOSClient


@dataclass
class TokenInfo:
    sub: str
    email: str
    role: str
    org_id: str | None
    token: str = ""
    api_url: str = ""


# Where cached login tokens live (~/.techneos/<env>_token.json). Override TECHNEOS_CONFIG_DIR.
DDT_CACHE_DIR = Path(os.environ.get("TECHNEOS_CONFIG_DIR", str(Path.home() / ".techneos")))


def _get_token_cache_path(env_name: str = "") -> Path:
    """Get the token cache file path, optionally specific to an environment.

    If env_name is provided, returns ``~/.techneos/{env_name}_token.json``.
    Otherwise, returns ``~/.techneos/token.json`` for backwards compatibility.
    """
    if env_name:
        return DDT_CACHE_DIR / f"{env_name}_token.json"
    return DDT_CACHE_DIR / "token.json"


def decode_jwt(token: str) -> dict[str, Any]:
    try:
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        decoded = base64.urlsafe_b64decode(payload_b64)
        return cast(dict[Any, Any], json.loads(decoded))
    except (IndexError, ValueError, json.JSONDecodeError):
        return {}


def _validate_token(token: str) -> TokenInfo | None:
    """Decode and validate a token. Returns TokenInfo if valid admin, None otherwise."""
    claims = decode_jwt(token)
    role = claims.get("role", "")
    if role not in ("platform_admin", "org_admin"):
        return None
    return TokenInfo(
        sub=claims.get("sub", ""),
        email=claims.get("email", ""),
        role=role,
        org_id=claims.get("org_id"),
        token=token,
    )


def check_admin_role(token: str) -> TokenInfo:
    info = _validate_token(token)
    if info is None:
        claims = decode_jwt(token)
        role = claims.get("role", "")
        print(
            f"Error: Access denied. Role '{role}' is not allowed. "
            "Only platform_admin or org_admin can perform this operation.",
            file=sys.stderr,
        )
        sys.exit(1)
    return info


def _load_cached_token(env_name: str = "") -> tuple[str, str] | None:
    """Load cached token and its associated api_url.

    Returns ``(token, api_url)`` or ``None`` if no cache exists.
    """
    token_cache = _get_token_cache_path(env_name)
    if not token_cache.exists():
        return None
    try:
        data = json.loads(token_cache.read_text())
        token = data.get("access_token") or data.get("token")
        base_url = data.get("base_url", "")
        if token:
            return token, base_url
        return None
    except (json.JSONDecodeError, OSError):
        return None


def _save_cached_token(token: str, api_url: str = "", env_name: str = "") -> None:
    token_cache = _get_token_cache_path(env_name)
    token_cache.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "access_token": token,
        "token": token,
        "base_url": api_url.rstrip("/") if api_url else "",
    }
    token_cache.write_text(json.dumps(data, indent=2))
    token_cache.chmod(0o600)


def _check_api_token(token: str, api_url: str) -> TokenInfo | None:
    """Validate a token by checking the /auth/me endpoint."""
    client = TechneOSClient(api_url=api_url, token=token)
    code, body = client.get("/api/v1/auth/me")
    if code != 200:
        return None

    try:
        data = json.loads(body)
        role = data.get("role", "")
        if role not in ("platform_admin", "org_admin"):
            return None

        return TokenInfo(
            sub=data.get("id", ""),
            email=data.get("email", ""),
            role=role,
            org_id=data.get("org_id"),
            token=token,
        )
    except json.JSONDecodeError:
        return None


def _login(api_url: str, email: str, password: str) -> str:
    payload = json.dumps(
        {
            "email": email,
            "password": password,
            "auth_method": "local",
        }
    ).encode()
    req = Request(f"{api_url}/api/v1/auth/login", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req) as resp:
            body = json.loads(resp.read().decode())
    except HTTPError as e:
        body = json.loads(e.read().decode())
        msg = body.get("detail", body.get("message", str(e)))
        print(f"Login failed: {msg}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Connection failed: {e.reason}", file=sys.stderr)
        sys.exit(1)

    token = body.get("access_token")
    if not token:
        print("Login failed: no access_token in response", file=sys.stderr)
        sys.exit(1)
    return cast(str, token)


def _prompt_login(api_url: str) -> str:
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    return _login(api_url, email, password)


def authenticate(api_url: str, env_name: str = "") -> TokenInfo:
    """Obtain a valid admin token from cache or interactive login.

    Priority:
    1. ``~/.techneos/{env_name}_token.json`` cache file (if env_name provided) or ``~/.techneos/token.json``
    2. Interactive prompt for email + password

    The obtained token and its ``api_url`` are saved to the environment-specific
    cache file so subsequent calls can reuse it without re-authenticating.

    Args:
        api_url: The API base URL to authenticate against
        env_name: Optional environment name (e.g., "dev", "staging", "prod")
                  to use environment-specific token caching
    """
    cached = _load_cached_token(env_name)
    if cached:
        cached_token, cached_url = cached
        if cached_url and cached_url.rstrip("/") != api_url.rstrip("/"):
            print(
                f"Cached token belongs to {cached_url}, targeting {api_url} — re-authenticating...",
            )
        else:
            info = _check_api_token(cached_token, api_url)
            if info is not None:
                cache_file = _get_token_cache_path(env_name)
                print(f"Using token from {cache_file}")
                info.api_url = api_url
                return info

            # If we're here, the token was invalid
            cache_file = _get_token_cache_path(env_name)
            print(f"Cached token in {cache_file} is expired or invalid, re-authenticating...")

    token = _prompt_login(api_url)
    info = _validate_token(token)
    if info is None:
        print("Error: Authenticated user does not have admin privileges.", file=sys.stderr)
        sys.exit(1)

    _save_cached_token(token, api_url, env_name)
    info.api_url = api_url
    print(f"Authenticated as {info.email}")
    return info
