"""Email repository. ``message_id`` is the idempotency key."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db.common import from_json, now_iso, to_json


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["headers"] = from_json(data.get("headers"))
    return data


def upsert_email(
    conn: sqlite3.Connection,
    *,
    message_id: str,
    thread_id: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    subject: str | None = None,
    body_text: str | None = None,
    headers: dict | None = None,
    received_at: str | None = None,
) -> int:
    """Insert the email if new; return its id. No-op on duplicate message_id.

    Idempotent: a second call with the same ``message_id`` does not create a
    second row and does not overwrite the existing one.
    """
    ts = now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO emails
                (message_id, thread_id, sender, recipient, subject, body_text,
                 headers, received_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(message_id) DO NOTHING
            """,
            (
                message_id,
                thread_id,
                sender,
                recipient,
                subject,
                body_text,
                to_json(headers),
                received_at,
                ts,
                ts,
            ),
        )
    row = conn.execute(
        "SELECT id FROM emails WHERE message_id = ?", (message_id,)
    ).fetchone()
    return int(row[0])


def get_email(conn: sqlite3.Connection, email_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_by_message_id(
    conn: sqlite3.Connection, message_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM emails WHERE message_id = ?", (message_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_emails(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if status is None:
        rows = conn.execute(
            "SELECT * FROM emails ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM emails WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_status(conn: sqlite3.Connection, email_id: int, status: str) -> None:
    with conn:
        conn.execute(
            "UPDATE emails SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso(), email_id),
        )


def set_triage(
    conn: sqlite3.Connection,
    email_id: int,
    category: str,
    *,
    status: str = "triaged",
) -> None:
    """Record the triage category and advance status (default ``triaged``)."""
    with conn:
        conn.execute(
            """
            UPDATE emails
            SET triage_category = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (category, status, now_iso(), email_id),
        )
