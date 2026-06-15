"""Database schema and idempotent bootstrap.

DDL for the five relational tables plus the ``sqlite-vec`` virtual table that
holds knowledge-base embeddings. ``bootstrap()`` is safe to call on every
startup. Embedding dimension matches ``text-embedding-3-small`` (1536).
"""

from __future__ import annotations

import re
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
        llm_provider         TEXT,            -- "openai"|"anthropic"|"github_models"
        embedding_provider   TEXT,            -- "openai"|"github_models"
        generation_model     TEXT,            -- optional model-id override
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


def _vector_ddl(dim: int) -> str:
    return f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vectors USING vec0(
        chunk_id  INTEGER PRIMARY KEY,
        embedding FLOAT[{dim}]
    );
    """

# Seed rows for the single-row config tables --------------------------------

_SEED_STATEMENTS: tuple[str, ...] = (
    "INSERT OR IGNORE INTO settings (id, updated_at) VALUES (1, ?);",
    "INSERT OR IGNORE INTO sync_state (id) VALUES (1);",
)


# Idempotent column adds for settings rows created by older schema versions.
_SETTINGS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("llm_provider", "TEXT"),
    ("embedding_provider", "TEXT"),
    ("generation_model", "TEXT"),
)


def _ensure_settings_columns(conn: sqlite3.Connection) -> None:
    """Add provider-selection columns to a pre-existing settings table."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(settings)")}
    for name, decl in _SETTINGS_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE settings ADD COLUMN {name} {decl}")


def bootstrap(conn: sqlite3.Connection) -> None:
    """Create relational tables + seed single-row config. Idempotent.

    The vector table is created separately via :func:`ensure_vector_table` so its
    embedding dimension can match the configured embedding provider.
    """
    with conn:  # single transaction; commits on success
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        _ensure_settings_columns(conn)
        conn.execute(_SEED_STATEMENTS[0], (now_iso(),))
        conn.execute(_SEED_STATEMENTS[1])


def ensure_vector_table(conn: sqlite3.Connection, dim: int = EMBEDDING_DIM) -> None:
    """Create the ``knowledge_vectors`` table at ``dim`` if it doesn't exist."""
    with conn:
        conn.execute(_vector_ddl(dim))


def vector_table_dim(conn: sqlite3.Connection) -> int | None:
    """Return the embedding dimension of the existing vector table, or None."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'knowledge_vectors'"
    ).fetchone()
    if not row or not row[0]:
        return None
    match = re.search(r"FLOAT\[(\d+)\]", row[0])
    return int(match.group(1)) if match else None


def recreate_vector_table(conn: sqlite3.Connection, dim: int) -> None:
    """Drop and recreate the vector table at ``dim`` (destroys stored vectors)."""
    with conn:
        conn.execute("DROP TABLE IF EXISTS knowledge_vectors")
        conn.execute(_vector_ddl(dim))
