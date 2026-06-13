"""Knowledge-base chunk repository.

Couples the relational ``knowledge_chunks`` table with the ``VectorStore`` so a
chunk and its embedding are written/deleted together, and search returns the
chunk rows ranked by vector distance.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db.common import from_json, now_iso, to_json
from app.db.vector_store.base import VectorStore


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = from_json(data.get("metadata"))
    return data


def add_chunk(
    conn: sqlite3.Connection,
    store: VectorStore,
    *,
    source_type: str,
    source_name: str,
    chunk_index: int,
    chunk_text: str,
    embedding: list[float],
    token_count: int | None = None,
    metadata: dict | None = None,
) -> int:
    """Insert a chunk + its embedding; return the new ``chunk_id``."""
    with conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_chunks
                (source_type, source_name, chunk_index, chunk_text,
                 token_count, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_type,
                source_name,
                chunk_index,
                chunk_text,
                token_count,
                to_json(metadata),
                now_iso(),
            ),
        )
        chunk_id = int(cur.lastrowid)
    store.add(chunk_id, embedding)
    return chunk_id


def get_chunk(conn: sqlite3.Connection, chunk_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM knowledge_chunks WHERE id = ?", (chunk_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_chunks(
    conn: sqlite3.Connection, *, source_name: str | None = None
) -> list[dict[str, Any]]:
    if source_name is None:
        rows = conn.execute(
            "SELECT * FROM knowledge_chunks ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM knowledge_chunks WHERE source_name = ? ORDER BY id",
            (source_name,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_chunk(
    conn: sqlite3.Connection, store: VectorStore, chunk_id: int
) -> None:
    """Delete a chunk and its embedding together."""
    with conn:
        conn.execute("DELETE FROM knowledge_chunks WHERE id = ?", (chunk_id,))
    store.delete(chunk_id)


def delete_by_source(
    conn: sqlite3.Connection, store: VectorStore, source_name: str
) -> int:
    """Delete all chunks for a source (and their embeddings). Returns count."""
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM knowledge_chunks WHERE source_name = ?",
            (source_name,),
        ).fetchall()
    ]
    for chunk_id in ids:
        delete_chunk(conn, store, chunk_id)
    return len(ids)


def search(
    conn: sqlite3.Connection,
    store: VectorStore,
    query_embedding: list[float],
    k: int,
) -> list[dict[str, Any]]:
    """KNN search: return chunk rows + ``distance``, nearest first."""
    hits = store.search(query_embedding, k)
    results: list[dict[str, Any]] = []
    for chunk_id, distance in hits:
        chunk = get_chunk(conn, chunk_id)
        if chunk is not None:  # skip if relational row vanished
            chunk["distance"] = distance
            results.append(chunk)
    return results
