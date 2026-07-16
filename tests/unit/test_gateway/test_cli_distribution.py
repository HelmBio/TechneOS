"""Tests for the gateway's techneos-cli distribution index."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.routes.cli import router

WHEEL = "techneos_cli-0.1.0-py3-none-any.whl"


@pytest.fixture
def wheel_dir(tmp_path, monkeypatch):
    """Point the gateway at a throwaway directory holding one wheel."""
    (tmp_path / WHEEL).write_bytes(b"PK\x03\x04 not-a-real-wheel")
    monkeypatch.setattr("gateway.routes.cli._wheel_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def client(wheel_dir):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestSimpleIndex:
    def test_root_index_lists_the_project(self, client):
        resp = client.get("/cli/simple/")
        assert resp.status_code == 200
        assert "/cli/simple/techneos-cli/" in resp.text

    def test_project_page_links_the_wheel(self, client):
        resp = client.get("/cli/simple/techneos-cli/")
        assert resp.status_code == 200
        assert f"/cli/dist/{WHEEL}" in resp.text

    @pytest.mark.parametrize("alias", ["techneos_cli", "Techneos-CLI", "techneos.cli"])
    def test_pep503_name_normalization(self, client, alias):
        # pip may request any of these spellings for the same project.
        resp = client.get(f"/cli/simple/{alias}/")
        assert resp.status_code == 200
        assert WHEEL in resp.text

    def test_unknown_project_forwards_upstream(self, client):
        # Lets this be a client's sole --index-url: the CLI's own dependencies
        # resolve through here rather than needing a second index.
        resp = client.get("/cli/simple/httpx/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://pypi.org/simple/httpx/"


class TestDownload:
    def test_serves_the_wheel(self, client):
        resp = client.get(f"/cli/dist/{WHEEL}")
        assert resp.status_code == 200
        assert resp.content == b"PK\x03\x04 not-a-real-wheel"

    def test_unknown_wheel_404s(self, client):
        resp = client.get("/cli/dist/techneos_cli-9.9.9-py3-none-any.whl")
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        "attack",
        [
            "../../../../etc/passwd",
            "..%2f..%2f..%2fetc%2fpasswd",
            "techneos_cli-0.1.0-py3-none-any.whl/../../../etc/passwd",
        ],
    )
    def test_cannot_escape_the_wheel_directory(self, client, attack):
        # Only files the index itself enumerates are servable.
        resp = client.get(f"/cli/dist/{attack}")
        assert resp.status_code == 404

    def test_only_cli_wheels_are_served(self, client, wheel_dir):
        # A stray file in the directory is not downloadable.
        (wheel_dir / "secrets.env").write_text("TOKEN=hunter2")
        assert client.get("/cli/dist/secrets.env").status_code == 404


class TestVersionEndpoint:
    def test_reports_the_served_version(self, client):
        body = client.get("/cli/version").json()
        assert body["cli_version"] == "0.1.0"
        assert body["wheel"] == WHEEL
        assert body["index_url"] == "/cli/simple/"


class TestSchemaVisibility:
    """Only /cli/version is documented; the index is for installers, not people."""

    @pytest.fixture
    def schema(self, wheel_dir):
        app = FastAPI()
        app.include_router(router, tags=["cli"])
        return app.openapi()

    def test_version_is_documented(self, schema):
        assert "/cli/version" in schema["paths"]

    @pytest.mark.parametrize(
        "path",
        ["/cli/simple/", "/cli/simple/{project}/", "/cli/dist/{filename}"],
    )
    def test_installer_facing_paths_are_not(self, schema, path):
        # They return HTML and binary wheels — a "Try it out" button on them is
        # noise, and they are only ever used via --index-url.
        assert path not in schema["paths"]


class TestNoWheelPresent:
    """A source checkout that never ran `make build-cli-wheel`."""

    @pytest.fixture
    def empty_client(self, tmp_path, monkeypatch):
        monkeypatch.setattr("gateway.routes.cli._wheel_dir", lambda: tmp_path / "nope")
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_version_404s_with_a_usable_hint(self, empty_client):
        resp = empty_client.get("/cli/version")
        assert resp.status_code == 404
        assert "make build-cli-wheel" in resp.json()["detail"]

    def test_project_page_404s(self, empty_client):
        assert empty_client.get("/cli/simple/techneos-cli/").status_code == 404

    def test_root_index_still_responds(self, empty_client):
        # The index itself is static; only the wheel listing needs a build.
        assert empty_client.get("/cli/simple/").status_code == 200
