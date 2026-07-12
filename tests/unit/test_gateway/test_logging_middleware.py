"""Tests for the gateway request logging middleware."""

import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gateway.middleware.logging import RequestLoggingMiddleware


@pytest.fixture
def app():
    _app = FastAPI()
    _app.add_middleware(RequestLoggingMiddleware)

    @_app.get("/test")
    async def test_endpoint(request: Request):
        return {"request_id": request.state.request_id}

    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestRequestLogging:
    def test_sets_request_id_in_state(self, client):
        resp = client.get("/test")
        assert resp.status_code == 200
        # request_id should be returned from the endpoint
        data = resp.json()
        assert "request_id" in data
        assert len(data["request_id"]) == 8

    def test_sets_x_request_id_header(self, client):
        resp = client.get("/test")
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) == 8

    def test_request_id_matches_header_and_state(self, client):
        resp = client.get("/test")
        assert resp.json()["request_id"] == resp.headers["x-request-id"]

    def test_logs_request_info(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="gateway.access"):
            client.get("/test")
        assert any(
            "GET" in record.message and "/test" in record.message for record in caplog.records
        )

    def test_logs_duration(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="gateway.access"):
            client.get("/test")
        assert any("ms" in record.message for record in caplog.records)
