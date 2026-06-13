"""Tests for the kiosk auth fix (Phase 1, item 7).

UI-supporting endpoints (/settings, /budget, /devices, /test-audio) must be
reachable from the device itself (loopback) without a token, so the kiosk works
without the API key ever being embedded in the served page — while LAN/remote
callers still need a valid Bearer token. /query and /text must stay strict.

These run in-process via FastAPI's TestClient (no network). The default
TestClient host is "testclient" (non-loopback); we monkeypatch _client_host to
simulate the kiosk's loopback origin.
"""
import pytest
from fastapi.testclient import TestClient

import api_server

client = TestClient(api_server.app)


def test_devices_rejects_non_loopback_without_token():
    # Default TestClient host is non-loopback and we send no token.
    resp = client.get("/devices")
    assert resp.status_code == 401


def test_devices_accepts_valid_token_from_non_loopback():
    resp = client.get("/devices", headers={"Authorization": f"Bearer {api_server.API_KEY}"})
    assert resp.status_code == 200


def test_devices_allows_loopback_without_token(monkeypatch):
    # Simulate the kiosk: request originates from the device itself.
    monkeypatch.setattr(api_server, "_client_host", lambda request: "127.0.0.1")
    resp = client.get("/devices")
    assert resp.status_code == 200


def test_query_stays_strict_even_from_loopback(monkeypatch):
    # /query is for remote clients and must NOT be loopback-exempt.
    monkeypatch.setattr(api_server, "_client_host", lambda request: "127.0.0.1")
    resp = client.post("/query")  # no token, no file
    assert resp.status_code != 200
    assert resp.status_code in (401, 403)
