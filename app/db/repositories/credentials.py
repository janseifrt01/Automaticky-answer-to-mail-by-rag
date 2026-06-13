"""Credential repository — stores only ciphertext (encryption done by caller)."""

from __future__ import annotations

import sqlite3

from app.db.common import now_iso


def save(
    conn: sqlite3.Connection,
    provider: str,
    account: str | None,
    secret_enc: bytes,
) -> None:
    """Insert or replace the encrypted credential blob for a provider."""
    with conn:
        conn.execute(
            """
            INSERT INTO credentials (provider, account, secret_enc, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                account = excluded.account,
                secret_enc = excluded.secret_enc,
                updated_at = excluded.updated_at
            """,
            (provider, account, secret_enc, now_iso()),
        )


def load(conn: sqlite3.Connection, provider: str) -> bytes | None:
    """Return the encrypted credential blob for a provider, or ``None``."""
    row = conn.execute(
        "SELECT secret_enc FROM credentials WHERE provider = ?", (provider,)
    ).fetchone()
    return row[0] if row else None


def get_account(conn: sqlite3.Connection, provider: str) -> str | None:
    row = conn.execute(
        "SELECT account FROM credentials WHERE provider = ?", (provider,)
    ).fetchone()
    return row[0] if row else None


def delete(conn: sqlite3.Connection, provider: str) -> None:
    with conn:
        conn.execute("DELETE FROM credentials WHERE provider = ?", (provider,))
