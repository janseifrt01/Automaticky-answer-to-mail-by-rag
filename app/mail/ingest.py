"""Ingestion: pull new mail through the facade into the emails repo.

``sync_once`` is the idempotent unit the Epic 5 scheduler will call. It fetches
new messages via the provider's opaque cursor, upserts each (idempotent on
``message_id``), and persists the new cursor.
"""

from __future__ import annotations

import sqlite3

from app.db.repositories import emails as emails_repo
from app.db.repositories import sync_state as sync_repo
from app.mail.base import MailProvider
from app.mail.models import EmailMessage


def _store(conn: sqlite3.Connection, msg: EmailMessage) -> bool:
    """Upsert one message; return True if it was newly inserted."""
    existed = emails_repo.get_by_message_id(conn, msg.provider_message_id) is not None
    emails_repo.upsert_email(
        conn,
        message_id=msg.provider_message_id,
        thread_id=msg.thread_id,
        sender=msg.sender,
        recipient=", ".join(msg.recipients),
        subject=msg.subject,
        body_text=msg.body_text,
        headers=msg.headers,
        received_at=msg.received_at,
    )
    return not existed


def sync_once(conn: sqlite3.Connection, provider: MailProvider) -> int:
    """Fetch and persist new mail. Returns the count of newly stored emails."""
    if not provider.is_connected():
        return 0
    cursor = sync_repo.get_history_id(conn)
    result = provider.fetch_new(cursor)
    new_count = sum(_store(conn, msg) for msg in result.messages)
    sync_repo.set_history_id(conn, result.cursor)
    return new_count
