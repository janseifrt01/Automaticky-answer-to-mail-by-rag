"""Reply repository. A reply is the AI draft linked to an email."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db.common import from_json, now_iso, to_json

# Columns callers may update via ``update_reply``.
_UPDATABLE = {
    "reply_text",
    "sources_used",
    "confidence",
    "should_send",
    "gmail_draft_id",
    "status",
}
# Columns stored as JSON text.
_JSON_FIELDS = {"sources_used"}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["sources_used"] = from_json(data.get("sources_used"))
    data["should_send"] = bool(data.get("should_send"))
    return data


def create_reply(
    conn: sqlite3.Connection,
    *,
    email_id: int,
    reply_text: str | None = None,
    sources_used: list | None = None,
    confidence: float | None = None,
    should_send: bool = False,
    gmail_draft_id: str | None = None,
    status: str = "draft",
) -> int:
    ts = now_iso()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO replies
                (email_id, reply_text, sources_used, confidence, should_send,
                 gmail_draft_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email_id,
                reply_text,
                to_json(sources_used),
                confidence,
                int(should_send),
                gmail_draft_id,
                status,
                ts,
                ts,
            ),
        )
        return int(cur.lastrowid)


def get_reply(conn: sqlite3.Connection, reply_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM replies WHERE id = ?", (reply_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_latest_for_email(
    conn: sqlite3.Connection, email_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM replies WHERE email_id = ? ORDER BY id DESC LIMIT 1",
        (email_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def update_reply(conn: sqlite3.Connection, reply_id: int, **fields: Any) -> None:
    """Update whitelisted columns. JSON fields are serialized automatically."""
    updates = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not updates:
        return
    sets: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        sets.append(f"{key} = ?")
        if key in _JSON_FIELDS:
            values.append(to_json(value))
        elif key == "should_send":
            values.append(int(bool(value)))
        else:
            values.append(value)
    values.extend([now_iso(), reply_id])
    with conn:
        conn.execute(
            f"UPDATE replies SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
            values,
        )
