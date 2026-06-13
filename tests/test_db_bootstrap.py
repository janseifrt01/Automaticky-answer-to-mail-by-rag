"""Tests for DB bootstrap and sqlite-vec loading (Task 0.4)."""

from __future__ import annotations

from app.db.connection import connect, vec_version
from app.db.schema import EMBEDDING_DIM, bootstrap

EXPECTED_TABLES = {
    "knowledge_chunks",
    "knowledge_vectors",
    "emails",
    "replies",
    "settings",
    "sync_state",
}


def _table_names(conn) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view');"
    ).fetchall()
    return {r[0] for r in rows}


def test_vec_extension_loads(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    try:
        assert vec_version(conn)  # non-empty version string
    finally:
        conn.close()


def test_bootstrap_creates_all_tables(tmp_db):
    names = _table_names(tmp_db)
    assert EXPECTED_TABLES <= names


def test_bootstrap_is_idempotent(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    try:
        bootstrap(conn)
        bootstrap(conn)  # second call must not raise
        # single-row config tables still hold exactly one seeded row
        (settings_count,) = conn.execute("SELECT COUNT(*) FROM settings;").fetchone()
        (sync_count,) = conn.execute("SELECT COUNT(*) FROM sync_state;").fetchone()
        assert settings_count == 1
        assert sync_count == 1
    finally:
        conn.close()


def test_vector_table_accepts_knn_query(tmp_db):
    # Insert two chunks + embeddings, then nearest-neighbour search.
    import sqlite_vec

    near = [0.0] * EMBEDDING_DIM
    far = [1.0] * EMBEDDING_DIM
    query = [0.0] * EMBEDDING_DIM

    tmp_db.execute(
        "INSERT INTO knowledge_vectors (chunk_id, embedding) VALUES (?, ?)",
        (1, sqlite_vec.serialize_float32(near)),
    )
    tmp_db.execute(
        "INSERT INTO knowledge_vectors (chunk_id, embedding) VALUES (?, ?)",
        (2, sqlite_vec.serialize_float32(far)),
    )
    rows = tmp_db.execute(
        """
        SELECT chunk_id FROM knowledge_vectors
        WHERE embedding MATCH ? ORDER BY distance LIMIT 1
        """,
        (sqlite_vec.serialize_float32(query),),
    ).fetchall()
    assert rows[0][0] == 1  # the 'near' chunk is closest
