"""Tests for the reply repository (Task 1.3)."""

from __future__ import annotations

import pytest
from app.db.repositories import emails, replies


@pytest.fixture
def email_id(tmp_db) -> int:
    return emails.upsert_email(tmp_db, message_id="m1", subject="Q")


def test_create_and_get_reply(tmp_db, email_id):
    rid = replies.create_reply(
        tmp_db,
        email_id=email_id,
        reply_text="answer",
        sources_used=[{"chunk_id": 1, "score": 0.9}],
        confidence=0.88,
        should_send=True,
    )
    row = replies.get_reply(tmp_db, rid)
    assert row["reply_text"] == "answer"
    assert row["sources_used"] == [{"chunk_id": 1, "score": 0.9}]
    assert row["should_send"] is True  # stored 0/1, read back as bool
    assert row["status"] == "draft"


def test_update_reply_whitelist_and_json(tmp_db, email_id):
    rid = replies.create_reply(tmp_db, email_id=email_id)
    replies.update_reply(
        tmp_db,
        rid,
        status="sent",
        gmail_draft_id="d123",
        sources_used=[{"chunk_id": 7}],
        bogus="ignored",  # not in whitelist
    )
    row = replies.get_reply(tmp_db, rid)
    assert row["status"] == "sent"
    assert row["gmail_draft_id"] == "d123"
    assert row["sources_used"] == [{"chunk_id": 7}]


def test_latest_for_email(tmp_db, email_id):
    replies.create_reply(tmp_db, email_id=email_id, reply_text="v1")
    second = replies.create_reply(tmp_db, email_id=email_id, reply_text="v2")
    latest = replies.get_latest_for_email(tmp_db, email_id)
    assert latest["id"] == second
    assert latest["reply_text"] == "v2"


def test_delete_email_cascades_replies(tmp_db, email_id):
    replies.create_reply(tmp_db, email_id=email_id, reply_text="x")
    with tmp_db:
        tmp_db.execute("DELETE FROM emails WHERE id = ?", (email_id,))
    (count,) = tmp_db.execute(
        "SELECT COUNT(*) FROM replies WHERE email_id = ?", (email_id,)
    ).fetchone()
    assert count == 0  # ON DELETE CASCADE
