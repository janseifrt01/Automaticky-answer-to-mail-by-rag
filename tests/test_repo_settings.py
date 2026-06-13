"""Tests for the settings repository (Task 1.4)."""

from __future__ import annotations

from app.db.repositories import settings


def test_defaults_present_after_bootstrap(tmp_db):
    row = settings.get_settings_row(tmp_db)
    assert row["id"] == 1
    assert row["reply_mode"] == "pilot"
    assert row["confidence_threshold"] == 0.75
    assert row["gmail_connected"] is False
    assert row["auto_send_rules"] is None


def test_update_round_trip(tmp_db):
    settings.update_settings(
        tmp_db,
        reply_mode="auto",
        confidence_threshold=0.6,
        gmail_connected=True,
        gmail_email="me@example.com",
        auto_send_rules={"keywords": ["invoice"]},
    )
    row = settings.get_settings_row(tmp_db)
    assert row["reply_mode"] == "auto"
    assert row["confidence_threshold"] == 0.6
    assert row["gmail_connected"] is True
    assert row["gmail_email"] == "me@example.com"
    assert row["auto_send_rules"] == {"keywords": ["invoice"]}


def test_update_with_no_known_fields_is_noop(tmp_db):
    before = settings.get_settings_row(tmp_db)
    settings.update_settings(tmp_db, not_a_column="x")
    after = settings.get_settings_row(tmp_db)
    assert before == after
