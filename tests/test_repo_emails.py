"""Tests for the email repository (Task 1.2)."""

from __future__ import annotations

from app.db.repositories import emails


def test_upsert_is_idempotent_on_message_id(tmp_db):
    first = emails.upsert_email(
        tmp_db, message_id="m1", sender="a@x.com", subject="Hi"
    )
    second = emails.upsert_email(
        tmp_db, message_id="m1", sender="changed@x.com", subject="Different"
    )
    assert first == second  # same row id
    (count,) = tmp_db.execute(
        "SELECT COUNT(*) FROM emails WHERE message_id = 'm1'"
    ).fetchone()
    assert count == 1
    # Original values preserved (no overwrite on conflict).
    row = emails.get_email(tmp_db, first)
    assert row["sender"] == "a@x.com"
    assert row["status"] == "pending"


def test_headers_json_round_trip(tmp_db):
    eid = emails.upsert_email(
        tmp_db,
        message_id="m2",
        headers={"List-Id": "<list.example.com>"},
    )
    row = emails.get_email(tmp_db, eid)
    assert row["headers"] == {"List-Id": "<list.example.com>"}


def test_get_by_message_id(tmp_db):
    emails.upsert_email(tmp_db, message_id="m3")
    row = emails.get_by_message_id(tmp_db, "m3")
    assert row is not None and row["message_id"] == "m3"
    assert emails.get_by_message_id(tmp_db, "nope") is None


def test_status_and_triage_updates(tmp_db):
    eid = emails.upsert_email(tmp_db, message_id="m4")
    emails.update_status(tmp_db, eid, "drafted")
    assert emails.get_email(tmp_db, eid)["status"] == "drafted"

    emails.set_triage(tmp_db, eid, "answerable")
    row = emails.get_email(tmp_db, eid)
    assert row["triage_category"] == "answerable"
    assert row["status"] == "triaged"


def test_list_emails_filters_by_status(tmp_db):
    a = emails.upsert_email(tmp_db, message_id="a")
    emails.upsert_email(tmp_db, message_id="b")
    emails.update_status(tmp_db, a, "sent")
    sent = emails.list_emails(tmp_db, status="sent")
    assert [e["message_id"] for e in sent] == ["a"]
    assert len(emails.list_emails(tmp_db)) == 2
