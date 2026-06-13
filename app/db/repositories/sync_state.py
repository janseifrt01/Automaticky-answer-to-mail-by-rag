"""Sync-state repository — the single ``id = 1`` row holding Gmail historyId."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db.common import now_iso


def get_sync_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the sync-state row (seeded at bootstrap, so always present)."""
    row = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
    return dict(row)


def get_history_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT last_history_id FROM sync_state WHERE id = 1"
    ).fetchone()
    return row[0] if row else None


def set_history_id(conn: sqlite3.Connection, history_id: str) -> None:
    """Persist the latest Gmail ``historyId`` and bump ``last_synced_at``."""
    with conn:
        conn.execute(
            """
            UPDATE sync_state
            SET last_history_id = ?, last_synced_at = ?
            WHERE id = 1
            """,
            (history_id, now_iso()),
        )
