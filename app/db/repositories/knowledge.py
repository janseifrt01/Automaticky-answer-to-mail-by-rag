"""Knowledge-base chunk repository.

Couples the relational ``knowledge_chunks`` table with the ``VectorStore`` so a
chunk and its embedding are written/deleted together, and search returns the
chunk rows ranked by vector distance. Chunks carry a ``namespace`` (default
``"default"``) — a forward-compat seam for per-topic streams; search/list/delete
can be scoped to one namespace.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db.common import from_json, now_iso, to_json
from app.db.vector_store.base import VectorStore

# When a namespace filter is applied we over-fetch KNN candidates, since the
# vector index isn't namespace-aware, then filter + trim to k.
_NAMESPACE_OVERSAMPLE = 5


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
    namespace: str = "default",
    token_count: int | None = None,
    metadata: dict | None = None,
) -> int:
    """Insert a chunk + its embedding; return the new ``chunk_id``."""
    with conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_chunks
                (namespace, source_type, source_name, chunk_index, chunk_text,
                 token_count, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                namespace,
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
    conn: sqlite3.Connection,
    *,
    source_name: str | None = None,
    namespace: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_name is not None:
        clauses.append("source_name = ?")
        params.append(source_name)
    if namespace is not None:
        clauses.append("namespace = ?")
        params.append(namespace)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM knowledge_chunks {where} ORDER BY id", params
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_sources(
    conn: sqlite3.Connection, *, namespace: str | None = None
) -> list[dict[str, Any]]:
    """Group chunks into their sources with counts (for the KB list UI)."""
    if namespace is None:
        rows = conn.execute(
            """
            SELECT namespace, source_name, source_type, COUNT(*) AS chunk_count
            FROM knowledge_chunks
            GROUP BY namespace, source_name, source_type
            ORDER BY source_name
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT namespace, source_name, source_type, COUNT(*) AS chunk_count
            FROM knowledge_chunks
            WHERE namespace = ?
            GROUP BY namespace, source_name, source_type
            ORDER BY source_name
            """,
            (namespace,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_chunk(
    conn: sqlite3.Connection, store: VectorStore, chunk_id: int
) -> None:
    """Delete a chunk and its embedding together."""
    with conn:
        conn.execute("DELETE FROM knowledge_chunks WHERE id = ?", (chunk_id,))
    store.delete(chunk_id)


def delete_by_source(
    conn: sqlite3.Connection,
    store: VectorStore,
    source_name: str,
    *,
    namespace: str | None = None,
) -> int:
    """Delete all chunks for a source (and their embeddings). Returns count."""
    if namespace is None:
        rows = conn.execute(
            "SELECT id FROM knowledge_chunks WHERE source_name = ?",
            (source_name,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM knowledge_chunks WHERE source_name = ? AND namespace = ?",
            (source_name, namespace),
        ).fetchall()
    ids = [r[0] for r in rows]
    for chunk_id in ids:
        delete_chunk(conn, store, chunk_id)
    return len(ids)


def search(
    conn: sqlite3.Connection,
    store: VectorStore,
    query_embedding: list[float],
    k: int,
    *,
    namespace: str | None = None,
) -> list[dict[str, Any]]:
    """KNN search: return chunk rows + ``distance``, nearest first.

    When ``namespace`` is given, over-fetch candidates and filter to that
    namespace (the vector index itself isn't namespace-partitioned).
    """
    fetch_k = k if namespace is None else k * _NAMESPACE_OVERSAMPLE
    hits = store.search(query_embedding, fetch_k)
    results: list[dict[str, Any]] = []
    for chunk_id, distance in hits:
        chunk = get_chunk(conn, chunk_id)
        if chunk is None:  # relational row vanished
            continue
        if namespace is not None and chunk.get("namespace") != namespace:
            continue
        chunk["distance"] = distance
        results.append(chunk)
        if len(results) >= k:
            break
    return results
