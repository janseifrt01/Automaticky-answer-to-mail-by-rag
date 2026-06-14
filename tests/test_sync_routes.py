"""Tests for the manual sync routes (Task 5.5)."""

from __future__ import annotations


def test_sync_now_returns_summary(client):
    # No mailbox connected and an empty inbox → a clean zero summary.
    resp = client.post("/sync/now")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["synced"] == 0


def test_sync_status_reports_last_run(client):
    assert client.get("/sync/status").json()["running"] is False
    client.post("/sync/now")
    status = client.get("/sync/status").json()
    assert status["running"] is False
    assert status["last_run"]["status"] == "ok"
