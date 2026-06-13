"""Tests for the FastAPI skeleton + health endpoint (Task 0.3)."""

from __future__ import annotations


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
