"""Settings repository — the single ``id = 1`` config row."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db.common import from_json, now_iso, to_json

# Columns callers may update (id/updated_at are managed here).
_UPDATABLE = {
    "gmail_connected",
    "gmail_email",
    "reply_mode",
    "confidence_threshold",
    "auto_send_rules",
    "llm_provider",
    "embedding_provider",
    "generation_model",
}
_JSON_FIELDS = {"auto_send_rules"}
_BOOL_FIELDS = {"gmail_connected"}


def get_settings_row(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the settings row (seeded at bootstrap, so always present)."""
    row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    data = dict(row)
    data["auto_send_rules"] = from_json(data.get("auto_send_rules"))
    data["gmail_connected"] = bool(data.get("gmail_connected"))
    return data


def update_settings(conn: sqlite3.Connection, **fields: Any) -> None:
    """Update whitelisted settings columns on the single config row."""
    updates = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not updates:
        return
    sets: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        sets.append(f"{key} = ?")
        if key in _JSON_FIELDS:
            values.append(to_json(value))
        elif key in _BOOL_FIELDS:
            values.append(int(bool(value)))
        else:
            values.append(value)
    values.append(now_iso())
    with conn:
        conn.execute(
            f"UPDATE settings SET {', '.join(sets)}, updated_at = ? WHERE id = 1",
            values,
        )
