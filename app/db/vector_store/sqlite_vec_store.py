"""``sqlite-vec`` implementation of :class:`VectorStore`.

Embeddings live in the ``knowledge_vectors`` virtual table inside the same
SQLite database as the relational data. The store wraps a ``sqlite3``
connection and serializes vectors with ``sqlite_vec.serialize_float32``.

Distance metric is the ``vec0`` default (**L2 / Euclidean**). OpenAI embeddings
are unit-normalized, so L2 ordering matches cosine ordering — keep embeddings
normalized so distances stay comparable.
"""

from __future__ import annotations

import sqlite3

import sqlite_vec


class SqliteVecStore:
    """Vector store backed by the ``knowledge_vectors`` virtual table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, chunk_id: int, embedding: list[float]) -> None:
        # vec0 virtual tables don't support UPSERT, so delete-then-insert to
        # make re-adding the same chunk_id idempotent.
        with self._conn:
            self._conn.execute(
                "DELETE FROM knowledge_vectors WHERE chunk_id = ?", (chunk_id,)
            )
            self._conn.execute(
                "INSERT INTO knowledge_vectors (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, sqlite_vec.serialize_float32(embedding)),
            )

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        rows = self._conn.execute(
            """
            SELECT chunk_id, distance
            FROM knowledge_vectors
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (sqlite_vec.serialize_float32(query), k),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def delete(self, chunk_id: int) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM knowledge_vectors WHERE chunk_id = ?",
                (chunk_id,),
            )
