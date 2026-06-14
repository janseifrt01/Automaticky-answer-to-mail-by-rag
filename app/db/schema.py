"""Database schema and idempotent bootstrap.

DDL for the five relational tables plus the ``sqlite-vec`` virtual table that
holds knowledge-base embeddings. ``bootstrap()`` is safe to call on every
startup. Embedding dimension matches ``text-embedding-3-small`` (1536).
"""

from __future__ import annotations

import sqlite3

from app.db.common import now_iso

EMBEDDING_DIM = 1536

# Relational tables ---------------------------------------------------------

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        namespace   TEXT NOT NULL DEFAULT 'default',  -- per-topic streams (fwd-compat)
        source_type TEXT NOT NULL,            -- 'file' | 'paste'
        source_name TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        chunk_text  TEXT NOT NULL,
        token_count INTEGER,
        metadata    TEXT,                     -- JSON
        created_at  TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_namespace ON knowledge_chunks(namespace);",
    """
    CREATE TABLE IF NOT EXISTS emails (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id      TEXT NOT NULL UNIQUE,
        thread_id       TEXT,
        sender          TEXT,
        recipient       TEXT,
        subject         TEXT,
        body_text       TEXT,
        headers         TEXT,                 -- JSON
        received_at     TEXT,
        triage_category TEXT,                 -- answerable|needs_human|no_reply
        status          TEXT NOT NULL DEFAULT 'pending',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);",
    "CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);",
    """
    CREATE TABLE IF NOT EXISTS replies (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id       INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
        reply_text     TEXT,
        sources_used   TEXT,                  -- JSON
        confidence     REAL,
        should_send    INTEGER NOT NULL DEFAULT 0,
        gmail_draft_id TEXT,
        status         TEXT NOT NULL DEFAULT 'draft',
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_replies_email ON replies(email_id);",
    """
    CREATE TABLE IF NOT EXISTS settings (
        id                   INTEGER PRIMARY KEY CHECK (id = 1),
        gmail_connected      INTEGER NOT NULL DEFAULT 0,
        gmail_email          TEXT,
        reply_mode           TEXT NOT NULL DEFAULT 'pilot',
        confidence_threshold REAL NOT NULL DEFAULT 0.75,
        auto_send_rules      TEXT,            -- JSON
        updated_at           TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        last_history_id TEXT,                 -- opaque sync cursor (Gmail historyId)
        last_synced_at  TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS credentials (
        provider   TEXT PRIMARY KEY,          -- e.g. 'gmail'
        account    TEXT,                      -- account email
        secret_enc BLOB NOT NULL,             -- Fernet-encrypted token JSON
        updated_at TEXT NOT NULL
    );
    """,
)

# Vector virtual table (sqlite-vec) -----------------------------------------

_VECTOR_STATEMENT = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vectors USING vec0(
    chunk_id  INTEGER PRIMARY KEY,
    embedding FLOAT[{EMBEDDING_DIM}]
);
"""

# Seed rows for the single-row config tables --------------------------------

_SEED_STATEMENTS: tuple[str, ...] = (
    "INSERT OR IGNORE INTO settings (id, updated_at) VALUES (1, ?);",
    "INSERT OR IGNORE INTO sync_state (id) VALUES (1);",
)


def bootstrap(conn: sqlite3.Connection) -> None:
    """Create all tables and seed single-row config. Idempotent."""
    with conn:  # single transaction; commits on success
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute(_VECTOR_STATEMENT)
        conn.execute(_SEED_STATEMENTS[0], (now_iso(),))
        conn.execute(_SEED_STATEMENTS[1])
