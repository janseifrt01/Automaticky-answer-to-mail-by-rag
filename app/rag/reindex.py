"""Rebuild the vector index when the embedding model / dimension changes.

Switching embedding provider (e.g. OpenAI 1536-dim → fastembed 384-dim) makes the
stored vectors incompatible. This recreates the vector table at the new model's
true dimension and re-embeds every knowledge chunk. Relational chunk rows are
untouched, so ``chunk_id``s are preserved.
"""

from __future__ import annotations

import sqlite3

from app.db.repositories import knowledge as kb_repo
from app.db.schema import recreate_vector_table
from app.db.vector_store.base import VectorStore
from app.providers.base import EmbeddingProvider

_BATCH = 100


def reindex_all(
    conn: sqlite3.Connection,
    store: VectorStore,
    embedder: EmbeddingProvider,
) -> tuple[int, int]:
    """Re-embed all chunks at the embedder's true dimension.

    Returns ``(chunks_indexed, dimension)``.
    """
    chunks = kb_repo.list_chunks(conn)
    # Probe the embedder for its real output dimension (authoritative).
    dim = len(embedder.embed(["dimension probe"])[0])
    recreate_vector_table(conn, dim)
    if not chunks:
        return 0, dim
    for start in range(0, len(chunks), _BATCH):
        batch = chunks[start : start + _BATCH]
        vectors = embedder.embed([c["chunk_text"] for c in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            store.add(chunk["id"], vector)
    return len(chunks), dim
