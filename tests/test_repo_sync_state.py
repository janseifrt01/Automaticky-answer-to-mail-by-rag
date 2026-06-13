"""Tests for the sync_state repository (Task 1.5)."""

from __future__ import annotations

from app.db.repositories import sync_state


def test_defaults_present_after_bootstrap(tmp_db):
    row = sync_state.get_sync_state(tmp_db)
    assert row["id"] == 1
    assert row["last_history_id"] is None
    assert sync_state.get_history_id(tmp_db) is None


def test_set_then_get_history_id(tmp_db):
    sync_state.set_history_id(tmp_db, "987654")
    assert sync_state.get_history_id(tmp_db) == "987654"
    row = sync_state.get_sync_state(tmp_db)
    assert row["last_synced_at"] is not None
