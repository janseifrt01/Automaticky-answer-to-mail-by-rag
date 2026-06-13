"""Tests for the sync_once ingestion service (Task 2.8)."""

from __future__ import annotations

from app.db.repositories import emails as emails_repo
from app.db.repositories import sync_state as sync_repo
from app.mail.ingest import sync_once

from tests.conftest import FakeMailProvider, make_email


def test_sync_once_stores_messages_and_advances_cursor(tmp_db, fake_mail_provider):
    new = sync_once(tmp_db, fake_mail_provider)
    assert new == 2
    assert len(emails_repo.list_emails(tmp_db)) == 2
    assert sync_repo.get_history_id(tmp_db) == "2"  # cursor = message count


def test_sync_once_is_idempotent(tmp_db, fake_mail_provider):
    assert sync_once(tmp_db, fake_mail_provider) == 2
    # Second run sees the same batch; nothing new is stored.
    assert sync_once(tmp_db, fake_mail_provider) == 0
    assert len(emails_repo.list_emails(tmp_db)) == 2


def test_sync_once_persists_message_fields(tmp_db):
    provider = FakeMailProvider(
        [make_email("m1", sender="bob@x.com", subject="Q", headers={"list-id": "<l>"})]
    )
    sync_once(tmp_db, provider)
    row = emails_repo.get_by_message_id(tmp_db, "m1")
    assert row["sender"] == "bob@x.com"
    assert row["subject"] == "Q"
    assert row["headers"] == {"list-id": "<l>"}


def test_sync_once_noop_when_disconnected(tmp_db):
    provider = FakeMailProvider([make_email("m1")], connected=False)
    assert sync_once(tmp_db, provider) == 0
    assert emails_repo.list_emails(tmp_db) == []
