"""Unit tests for the single-source package-index derivation in
``management.registration``: a catalog repo configures only
``PYTHON_PACKAGE_INDEX_URL`` / ``UV_DEFAULT_INDEX`` and the wheel publish URL, the
CodeArtifact token coordinates, and the ECR registry are derived from it.
Explicit env vars still win so the monorepo deploy is unchanged.
"""

from __future__ import annotations

import pytest

from management import registration
from management.registration import (
    _index_publish_url,
    _is_codeartifact_url,
    _parse_codeartifact_coords,
    add_auth_args,
    add_env_arg,
    auth_headers,
    find_resource_by_slug,
    load_env_file,
    make_publish_parser,
    package_index_url,
    read_package_meta,
    resolve_ecr_registry,
    resolve_image_repo,
    resolve_org_id,
    resolve_publish_credentials,
)

CA_INDEX = (
    "https://techneos-123456789012.d.codeartifact.us-east-1.amazonaws.com"
    "/pypi/techneos-tools/simple/"
)
CA_PUBLISH = (
    "https://techneos-123456789012.d.codeartifact.us-east-1.amazonaws.com/pypi/techneos-tools/"
)
DEVPI_INDEX = "http://localhost:3141/simple/"


@pytest.fixture(autouse=True)
def _clear_index_env(monkeypatch):
    # Start each test from a clean slate — no inherited build/publish config.
    for var in (
        "PYTHON_PACKAGE_INDEX_URL", "UV_DEFAULT_INDEX", "PYTHON_PACKAGE_PUBLISH_URL",
        "PYTHON_PACKAGE_USERNAME", "PYTHON_PACKAGE_PASSWORD",
        "CODEARTIFACT_DOMAIN", "CODEARTIFACT_DOMAIN_OWNER",
        "AWS_ACCOUNT_ID", "AWS_REGION",
    ):
        monkeypatch.delenv(var, raising=False)


def test_package_index_url_prefers_techneos_var(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", CA_INDEX)
    monkeypatch.setenv("UV_DEFAULT_INDEX", DEVPI_INDEX)
    assert package_index_url() == CA_INDEX


def test_package_index_url_strips_injected_credentials(monkeypatch):
    monkeypatch.setenv(
        "UV_DEFAULT_INDEX",
        "https://aws:sometok@techneos-123456789012.d.codeartifact.us-east-1.amazonaws.com"
        "/pypi/techneos-tools/simple/",
    )
    assert package_index_url() == CA_INDEX


def test_package_index_url_none_when_unset():
    assert package_index_url() is None


@pytest.mark.parametrize(
    "index, expected",
    [
        (CA_INDEX, CA_PUBLISH),
        (DEVPI_INDEX, "http://localhost:3141/"),
        ("http://localhost:3141/", "http://localhost:3141/"),
    ],
)
def test_index_publish_url(index, expected):
    assert _index_publish_url(index) == expected


def test_parse_codeartifact_coords():
    assert _parse_codeartifact_coords(CA_INDEX) == (
        "techneos", "123456789012", "us-east-1",
    )
    assert _parse_codeartifact_coords(DEVPI_INDEX) is None
    assert _parse_codeartifact_coords(None) is None


def test_publish_url_derived_from_index_devpi(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", DEVPI_INDEX)
    publish_url, username, password = resolve_publish_credentials()
    assert publish_url == "http://localhost:3141/"
    assert (username, password) == ("devpi", "devpi")


def test_publish_url_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", DEVPI_INDEX)
    monkeypatch.setenv("PYTHON_PACKAGE_PUBLISH_URL", "http://other:3141/")
    publish_url, _, _ = resolve_publish_credentials()
    assert publish_url == "http://other:3141/"


def test_ecr_registry_derived_from_index(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", CA_INDEX)
    assert (
        resolve_ecr_registry("prod")
        == "123456789012.dkr.ecr.us-east-1.amazonaws.com"
    )


def test_ecr_registry_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", CA_INDEX)
    monkeypatch.setenv("AWS_ACCOUNT_ID", "999999999999")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    assert (
        resolve_ecr_registry("prod") == "999999999999.dkr.ecr.eu-west-1.amazonaws.com"
    )


def test_ecr_registry_none_for_local(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_INDEX_URL", DEVPI_INDEX)
    assert resolve_ecr_registry("local") is None


# ── _is_codeartifact_url ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        (CA_INDEX, True),
        (DEVPI_INDEX, False),
        ("http://localhost:3141/", False),
        (None, False),
        ("", False),
    ],
)
def test_is_codeartifact_url(url, expected):
    assert _is_codeartifact_url(url) is expected


# ── resolve_publish_credentials: CodeArtifact path (token minting) ─────────────


def test_publish_credentials_codeartifact_mints_token(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_PUBLISH_URL", CA_PUBLISH)
    monkeypatch.setattr(registration, "_mint_codeartifact_token", lambda: "minted-tok")
    url, user, password = resolve_publish_credentials()
    assert url == CA_PUBLISH
    assert user == "aws"  # CodeArtifact requires username "aws"
    assert password == "minted-tok"


def test_publish_credentials_codeartifact_exits_when_mint_fails(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_PUBLISH_URL", CA_PUBLISH)
    monkeypatch.setattr(registration, "_mint_codeartifact_token", lambda: None)
    with pytest.raises(SystemExit):
        resolve_publish_credentials()


def test_publish_credentials_custom_devpi_creds(monkeypatch):
    monkeypatch.setenv("PYTHON_PACKAGE_PUBLISH_URL", "http://localhost:3141/")
    monkeypatch.setenv("PYTHON_PACKAGE_USERNAME", "alice")
    monkeypatch.setenv("PYTHON_PACKAGE_PASSWORD", "s3cret")
    _, user, password = resolve_publish_credentials()
    assert (user, password) == ("alice", "s3cret")


# ── resolve_image_repo ─────────────────────────────────────────────────────────


def test_resolve_image_repo_local():
    assert resolve_image_repo("local") == "techneos"


def test_resolve_image_repo_prod(monkeypatch):
    monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    assert resolve_image_repo("prod") == (
        "123456789012.dkr.ecr.us-east-1.amazonaws.com/techneos"
    )


def test_resolve_ecr_registry_prod_exits_without_account(monkeypatch, capsys):
    # No AWS_ACCOUNT_ID and no CodeArtifact index to derive it from.
    with pytest.raises(SystemExit):
        resolve_ecr_registry("prod")
    assert "cannot resolve the AWS account" in capsys.readouterr().err


# ── auth_headers ───────────────────────────────────────────────────────────────


def test_auth_headers_default_json():
    h = auth_headers("tok123")
    assert h["Authorization"] == "Bearer tok123"
    assert h["Accept"] == "application/json"
    assert h["Content-Type"] == "application/json"


def test_auth_headers_drops_content_type_for_multipart():
    h = auth_headers("tok", content_type=None)
    assert "Content-Type" not in h
    assert h["Authorization"] == "Bearer tok"


# ── read_package_meta ──────────────────────────────────────────────────────────


def test_read_package_meta_minimal(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "techneos-widget"\nversion = "1.2.3"\n'
    )
    meta = read_package_meta(tmp_path)
    assert meta.name == "techneos-widget"
    assert meta.version == "1.2.3"
    assert meta.entry_point is None and meta.docker_image is None


def test_read_package_meta_with_techneos_table(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "t"\nversion = "0.1.0"\n'
        '[tool.techneos]\nentry_point = "pkg.mod:run"\ndocker_image = "techneos/x"\n'
    )
    meta = read_package_meta(tmp_path)
    assert meta.entry_point == "pkg.mod:run"
    assert meta.docker_image == "techneos/x"


# ── load_env_file ──────────────────────────────────────────────────────────────


def test_load_env_file_none_env_returns_none():
    assert load_env_file(None) is None


def test_load_env_file_missing_returns_none(monkeypatch, tmp_path):
    # Point the module at a repo root with no env files.
    monkeypatch.setattr(
        registration.Path, "resolve", lambda self: tmp_path / "a/b/c/d/e/registration.py"
    )
    # Even if resolution is odd, a non-existent env file yields None.
    assert load_env_file("prod") is None


# ── HTTP helpers (httpx mocked) ────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, status_code=200, payload=None, success=True):
        self.status_code = status_code
        self._payload = payload or {}
        self.is_success = success

    def json(self):
        return self._payload


def test_resolve_org_id_success(monkeypatch):
    monkeypatch.setattr(
        registration.httpx, "get", lambda url, headers: _FakeResp(payload={"org_id": "org-7"})
    )
    assert resolve_org_id("http://localhost:8000", {}) == "org-7"


def test_resolve_org_id_http_error_exits(monkeypatch):
    monkeypatch.setattr(
        registration.httpx, "get",
        lambda url, headers: _FakeResp(status_code=500, success=False),
    )
    with pytest.raises(SystemExit):
        resolve_org_id("http://localhost:8000", {})


def test_resolve_org_id_no_org_exits(monkeypatch):
    monkeypatch.setattr(
        registration.httpx, "get", lambda url, headers: _FakeResp(payload={"org_id": None})
    )
    with pytest.raises(SystemExit):
        resolve_org_id("http://localhost:8000", {})


def test_find_resource_by_slug_found(monkeypatch):
    payload = {"items": [{"slug": "a", "id": "id-a"}, {"slug": "b", "id": "id-b"}]}
    monkeypatch.setattr(registration.httpx, "get", lambda url, headers: _FakeResp(payload=payload))
    assert find_resource_by_slug("http://x", {}, "/api/v1/tools", "b") == "id-b"


def test_find_resource_by_slug_not_found(monkeypatch):
    monkeypatch.setattr(
        registration.httpx, "get", lambda url, headers: _FakeResp(payload={"items": []})
    )
    assert find_resource_by_slug("http://x", {}, "/api/v1/tools", "missing") is None


def test_find_resource_by_slug_http_error(monkeypatch):
    monkeypatch.setattr(
        registration.httpx, "get", lambda url, headers: _FakeResp(success=False)
    )
    assert find_resource_by_slug("http://x", {}, "/api/v1/tools", "a") is None


# ── argparse helpers ───────────────────────────────────────────────────────────


def test_add_env_arg_defaults_local():
    import argparse

    p = argparse.ArgumentParser()
    add_env_arg(p)
    assert p.parse_args([]).env == "local"
    assert p.parse_args(["--env", "prod"]).env == "prod"


def test_add_env_arg_rejects_unknown_env():
    import argparse

    p = argparse.ArgumentParser()
    add_env_arg(p)
    with pytest.raises(SystemExit):
        p.parse_args(["--env", "bogus"])


def test_add_auth_args():
    import argparse

    p = argparse.ArgumentParser()
    add_auth_args(p)
    ns = p.parse_args(["--email", "a@b", "--password", "pw"])
    assert ns.email == "a@b" and ns.password == "pw"


def test_make_publish_parser_has_skip_register():
    p = make_publish_parser("publish the widget wheel")
    ns = p.parse_args(["--env", "prod", "--skip-register"])
    assert ns.env == "prod" and ns.skip_register is True
