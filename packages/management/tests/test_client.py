"""Tests for management.client.TechneOSClient — the thin urllib HTTP wrapper the
management wheel uses to reach the gateway. The transport (urllib) is mocked."""

from __future__ import annotations

import json
import urllib.error

from management import client as client_mod
from management.client import TechneOSClient


class _FakeResp:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture_urlopen(monkeypatch, status=200, body="{}"):
    """Patch urlopen to record the Request and return a canned response."""
    captured = {}

    def _fake(req):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        return _FakeResp(status, body)

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", _fake)
    return captured


def test_api_url_trailing_slash_stripped():
    assert TechneOSClient("http://localhost:8000/").api_url == "http://localhost:8000"


def test_get_success(monkeypatch):
    cap = _capture_urlopen(monkeypatch, 200, '{"ok": true}')
    code, body = TechneOSClient("http://x").get("/api/v1/health")
    assert code == 200 and json.loads(body) == {"ok": True}
    assert cap["method"] == "GET"
    assert cap["url"] == "http://x/api/v1/health"


def test_bearer_header_set_when_token_present(monkeypatch):
    cap = _capture_urlopen(monkeypatch)
    TechneOSClient("http://x", token="tok-1").get("/p")
    # urllib capitalizes header names.
    assert cap["headers"].get("Authorization") == "Bearer tok-1"


def test_no_auth_header_without_token(monkeypatch):
    cap = _capture_urlopen(monkeypatch)
    TechneOSClient("http://x").get("/p")
    assert "Authorization" not in cap["headers"]


def test_post_sends_json_body_and_content_type(monkeypatch):
    cap = _capture_urlopen(monkeypatch, 201, "{}")
    code, _ = TechneOSClient("http://x").post("/p", {"a": 1})
    assert code == 201
    assert cap["method"] == "POST"
    assert json.loads(cap["data"]) == {"a": 1}
    assert cap["headers"].get("Content-type") == "application/json"


def test_delete(monkeypatch):
    cap = _capture_urlopen(monkeypatch, 204, "")
    code, _ = TechneOSClient("http://x").delete("/p/1")
    assert code == 204 and cap["method"] == "DELETE"


def test_http_error_returns_code_and_body(monkeypatch):
    def _raise(req):
        import io

        raise urllib.error.HTTPError("http://x/p", 404, "Not Found", {}, io.BytesIO(b"missing"))

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", _raise)
    code, body = TechneOSClient("http://x").get("/p")
    assert code == 404 and body == "missing"


def test_url_error_returns_zero(monkeypatch):
    def _raise(req):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", _raise)
    code, body = TechneOSClient("http://x").get("/p")
    assert code == 0 and "connection refused" in body


def test_delete_storage_files_posts_to_admin_endpoint(monkeypatch):
    cap = _capture_urlopen(monkeypatch, 200, '{"deleted": [], "errors": []}')
    files = [{"bucket": "techneos-data", "key": "a/b.txt"}]
    code, _ = TechneOSClient("http://x").delete_storage_files(files)
    assert code == 200
    assert cap["url"].endswith("/api/v1/admin/storage/files/delete")
    assert json.loads(cap["data"]) == {"files": files}


# ── paginate ───────────────────────────────────────────────────────────────────


def test_paginate_walks_all_pages(monkeypatch):
    pages = [
        json.dumps({"items": [{"id": 1}, {"id": 2}], "total": 3}),
        json.dumps({"items": [{"id": 3}], "total": 3}),
    ]
    calls = {"n": 0}

    def _fake(req):
        body = pages[calls["n"]]
        calls["n"] += 1
        return _FakeResp(200, body)

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", _fake)
    items = TechneOSClient("http://x").paginate("/api/v1/tools", limit=2)
    assert [i["id"] for i in items] == [1, 2, 3]


def test_paginate_applies_filter(monkeypatch):
    body = json.dumps({"items": [{"id": 1, "keep": True}, {"id": 2, "keep": False}], "total": 2})
    monkeypatch.setattr(client_mod.urllib.request, "urlopen", lambda req: _FakeResp(200, body))
    items = TechneOSClient("http://x").paginate("/p", limit=100, filter_fn=lambda i: i["keep"])
    assert [i["id"] for i in items] == [1]


def test_paginate_stops_on_error(monkeypatch):
    monkeypatch.setattr(client_mod.urllib.request, "urlopen", lambda req: _FakeResp(500, "err"))
    assert TechneOSClient("http://x").paginate("/p") == []


def test_paginate_handles_bare_list_response(monkeypatch):
    # Endpoint returns a raw list, not a {items,total} envelope.
    body = json.dumps([{"id": 1}, {"id": 2}])
    monkeypatch.setattr(client_mod.urllib.request, "urlopen", lambda req: _FakeResp(200, body))
    items = TechneOSClient("http://x").paginate("/p", limit=100)
    assert [i["id"] for i in items] == [1, 2]
