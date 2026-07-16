"""Tests for client/platform version-skew detection."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.client_version import WARNING_HEADER, compatibility_warning
from gateway.middleware.client_version import ClientVersionMiddleware


class TestCompatibilityWarning:
    """The 0.x/1.x split is the whole point of the rule, so pin both sides."""

    def test_exact_match_is_silent(self):
        assert compatibility_warning("0.1.0", "0.1.0") == ""

    def test_patch_drift_is_silent(self):
        # Patch releases are compatible on either side of 1.0.
        assert compatibility_warning("0.1.7", "0.1.0") == ""
        assert compatibility_warning("1.2.9", "1.2.0") == ""

    def test_minor_drift_warns_below_1_0(self):
        # Semver allows 0.x minor bumps to break the API.
        assert compatibility_warning("0.2.0", "0.1.0") != ""
        assert compatibility_warning("0.1.0", "0.2.0") != ""

    def test_minor_drift_is_silent_from_1_0(self):
        # Warning here would fire on every routine platform release.
        assert compatibility_warning("1.1.0", "1.4.0") == ""

    def test_major_drift_warns(self):
        assert compatibility_warning("1.0.0", "2.0.0") != ""
        assert compatibility_warning("1.0.0", "0.1.0") != ""

    def test_warning_names_both_versions(self):
        warning = compatibility_warning("0.2.0", "0.1.0")
        assert "0.2.0" in warning
        assert "0.1.0" in warning

    def test_warning_uses_the_callers_own_url(self):
        # The fix has to be copy-pasteable, so it names the real host.
        warning = compatibility_warning("0.2.0", "0.1.0", base_url="https://techneos.acme.com/")
        assert "https://techneos.acme.com/cli/simple/" in warning
        assert "<platform-url>" not in warning

    def test_warning_falls_back_to_a_placeholder(self):
        assert "<platform-url>" in compatibility_warning("0.2.0", "0.1.0")

    @pytest.mark.parametrize("garbage", ["", "not-a-version", "v1", "1"])
    def test_unparseable_version_is_silent(self, garbage):
        # Never fail a request over a version string we can't read.
        assert compatibility_warning(garbage, "0.1.0") == ""

    def test_prerelease_and_local_suffixes_parse(self):
        assert compatibility_warning("0.1.0rc1", "0.1.0") == ""
        assert compatibility_warning("0.2.0.dev3", "0.1.0") != ""


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(ClientVersionMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return TestClient(app)


class TestClientVersionMiddleware:
    def test_no_header_no_warning(self, client):
        # Browsers, curl and the portal must be left alone.
        resp = client.get("/health")
        assert WARNING_HEADER not in resp.headers

    def test_matching_client_no_warning(self, client):
        resp = client.get("/health", headers={"X-Client-Version": "0.1.0"})
        assert WARNING_HEADER not in resp.headers

    def test_skewed_client_warned(self, client):
        resp = client.get("/health", headers={"X-Client-Version": "9.9.9"})
        assert WARNING_HEADER in resp.headers
        assert "9.9.9" in resp.headers[WARNING_HEADER]

    def test_warning_is_advisory_only(self, client):
        # The request is still served — skew never blocks.
        resp = client.get("/health", headers={"X-Client-Version": "9.9.9"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
