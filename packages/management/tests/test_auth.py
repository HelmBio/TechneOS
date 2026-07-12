"""Tests for management.auth — admin-token decoding, caching, and login.

The management wheel talks to the platform only over the gateway REST API, so
everything here is exercised with the HTTP layer (``urlopen`` / ``TechneOSClient``)
and the filesystem token cache mocked.
"""

from __future__ import annotations

import base64
import json

import pytest

from management import auth


def _make_jwt(claims: dict) -> str:
    """Build a JWT whose payload segment decodes to ``claims`` (signature ignored)."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


@pytest.fixture(autouse=True)
def _cache_in_tmp(tmp_path, monkeypatch):
    """Redirect the token cache into a temp dir (DDT_CACHE_DIR is import-time)."""
    monkeypatch.setattr(auth, "DDT_CACHE_DIR", tmp_path)
    return tmp_path


# ── decode_jwt ───────────────────────────────────────────────────────────────


def test_decode_jwt_valid():
    token = _make_jwt({"sub": "u1", "email": "a@b.com", "role": "platform_admin"})
    claims = auth.decode_jwt(token)
    assert claims["sub"] == "u1"
    assert claims["role"] == "platform_admin"


def test_decode_jwt_handles_missing_padding():
    # A payload whose length isn't a multiple of 4 must still decode.
    token = _make_jwt({"role": "org_admin", "org_id": "org-9"})
    assert auth.decode_jwt(token)["org_id"] == "org-9"


@pytest.mark.parametrize("bad", ["", "not-a-jwt", "only.two", "a.!!!.c"])
def test_decode_jwt_malformed_returns_empty(bad):
    assert auth.decode_jwt(bad) == {}


# ── _validate_token / check_admin_role ────────────────────────────────────────


@pytest.mark.parametrize("role", ["platform_admin", "org_admin"])
def test_validate_token_admin_roles(role):
    info = auth._validate_token(_make_jwt({"sub": "u", "email": "e", "role": role}))
    assert info is not None
    assert info.role == role


@pytest.mark.parametrize("role", ["scientist", "viewer", "", "project_lead"])
def test_validate_token_rejects_non_admin(role):
    assert auth._validate_token(_make_jwt({"role": role})) is None


def test_check_admin_role_returns_info_for_admin():
    info = auth.check_admin_role(_make_jwt({"sub": "u1", "email": "a@b", "role": "platform_admin"}))
    assert info.sub == "u1"


def test_check_admin_role_exits_for_non_admin(capsys):
    with pytest.raises(SystemExit) as exc:
        auth.check_admin_role(_make_jwt({"role": "scientist"}))
    assert exc.value.code == 1
    assert "Access denied" in capsys.readouterr().err


# ── token cache round-trip ─────────────────────────────────────────────────────


def test_save_and_load_cached_token(_cache_in_tmp):
    auth._save_cached_token("tok-abc", "http://localhost:8000/", env_name="dev")
    cache_file = _cache_in_tmp / "dev_token.json"
    assert cache_file.exists()
    # Permission is tightened to owner-only.
    assert (cache_file.stat().st_mode & 0o777) == 0o600
    loaded = auth._load_cached_token("dev")
    assert loaded == ("tok-abc", "http://localhost:8000")  # trailing slash stripped


def test_load_cached_token_missing_returns_none():
    assert auth._load_cached_token("nope") is None


def test_load_cached_token_corrupt_returns_none(_cache_in_tmp):
    (_cache_in_tmp / "bad_token.json").write_text("{not json")
    assert auth._load_cached_token("bad") is None


def test_default_cache_path_has_no_env_prefix():
    assert auth._get_token_cache_path().name == "token.json"
    assert auth._get_token_cache_path("staging").name == "staging_token.json"


# ── _check_api_token (gateway /auth/me) ────────────────────────────────────────


class _FakeClient:
    def __init__(self, code, body, **_):
        self._code = code
        self._body = body

    def get(self, _path):
        return self._code, self._body


def _patch_client(monkeypatch, code, body):
    monkeypatch.setattr(
        auth, "TechneOSClient", lambda **kw: _FakeClient(code, body)
    )


def test_check_api_token_valid_admin(monkeypatch):
    _patch_client(monkeypatch, 200, json.dumps({"id": "u1", "email": "a@b", "role": "org_admin"}))
    info = auth._check_api_token("tok", "http://localhost:8000")
    assert info is not None and info.role == "org_admin" and info.sub == "u1"


def test_check_api_token_non_200(monkeypatch):
    _patch_client(monkeypatch, 401, "unauthorized")
    assert auth._check_api_token("tok", "http://x") is None


def test_check_api_token_non_admin(monkeypatch):
    _patch_client(monkeypatch, 200, json.dumps({"role": "viewer"}))
    assert auth._check_api_token("tok", "http://x") is None


def test_check_api_token_bad_json(monkeypatch):
    _patch_client(monkeypatch, 200, "not json")
    assert auth._check_api_token("tok", "http://x") is None


# ── _login ─────────────────────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_login_returns_access_token(monkeypatch):
    monkeypatch.setattr(auth, "urlopen", lambda req: _FakeResp({"access_token": "tok-xyz"}))
    assert auth._login("http://localhost:8000", "a@b", "pw") == "tok-xyz"


def test_login_no_token_exits(monkeypatch, capsys):
    monkeypatch.setattr(auth, "urlopen", lambda req: _FakeResp({}))
    with pytest.raises(SystemExit):
        auth._login("http://localhost:8000", "a@b", "pw")
    assert "no access_token" in capsys.readouterr().err


def test_login_http_error_exits(monkeypatch, capsys):
    from urllib.error import HTTPError

    def _raise(req):
        raise HTTPError("url", 401, "Unauthorized", {}, _io(json.dumps({"detail": "bad creds"})))

    monkeypatch.setattr(auth, "urlopen", _raise)
    with pytest.raises(SystemExit):
        auth._login("http://localhost:8000", "a@b", "pw")
    assert "bad creds" in capsys.readouterr().err


def _io(text: str):
    import io

    return io.BytesIO(text.encode())


# ── authenticate (cache → prompt) ───────────────────────────────────────────────


def test_authenticate_uses_valid_cache(monkeypatch, _cache_in_tmp, capsys):
    auth._save_cached_token("cached-tok", "http://localhost:8000", env_name="dev")
    monkeypatch.setattr(
        auth,
        "_check_api_token",
        lambda t, u: auth.TokenInfo(sub="u1", email="a@b", role="platform_admin", org_id=None, token=t),
    )
    info = auth.authenticate("http://localhost:8000", env_name="dev")
    assert info.token == "cached-tok"
    assert info.api_url == "http://localhost:8000"


def test_authenticate_prompts_when_no_cache(monkeypatch, _cache_in_tmp):
    monkeypatch.setattr(auth, "_prompt_login", lambda url: _make_jwt(
        {"sub": "u2", "email": "admin@b", "role": "platform_admin"}
    ))
    info = auth.authenticate("http://localhost:8000", env_name="dev")
    assert info.email == "admin@b"
    # A fresh token was cached for reuse.
    assert (_cache_in_tmp / "dev_token.json").exists()


def test_authenticate_rejects_non_admin_login(monkeypatch, _cache_in_tmp, capsys):
    monkeypatch.setattr(auth, "_prompt_login", lambda url: _make_jwt({"role": "scientist"}))
    with pytest.raises(SystemExit):
        auth.authenticate("http://localhost:8000", env_name="dev")
    assert "does not have admin privileges" in capsys.readouterr().err


def test_authenticate_reauths_when_cache_targets_other_url(monkeypatch, _cache_in_tmp, capsys):
    auth._save_cached_token("old-tok", "https://other.example.com", env_name="dev")
    monkeypatch.setattr(auth, "_prompt_login", lambda url: _make_jwt(
        {"sub": "u", "email": "a@b", "role": "org_admin"}
    ))
    auth.authenticate("http://localhost:8000", env_name="dev")
    assert "re-authenticating" in capsys.readouterr().out
