"""Knowledge ingestion: parse → chunk → embed → index.

Writes chunks + embeddings through the Epic 1 ``knowledge`` repo / VectorStore.
Re-ingesting the same ``(namespace, source_name)`` replaces the prior version so
ingestion is idempotent.
"""

from __future__ import annotations

import sqlite3

from app.db.repositories import knowledge as kb_repo
from app.db.vector_store.base import VectorStore
from app.providers.base import EmbeddingProvider


def ingest_text(
    conn: sqlite3.Connection,
    store: VectorStore,
    provider: EmbeddingProvider,
    *,
    source_type: str,
    source_name: str,
    text: str,
    namespace: str = "default",
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> int:
    """Chunk + embed + index ``text``; return the number of chunks stored.

    Replaces any existing chunks for the same ``(namespace, source_name)``.
    """
    from app.rag.chunking import chunk_text

    chunks = chunk_text(text, size=chunk_size, overlap=chunk_overlap)

    # Idempotency: clear the previous version of this source first.
    kb_repo.delete_by_source(conn, store, source_name, namespace=namespace)
    if not chunks:
        return 0

    embeddings = provider.embed(chunks)
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
        kb_repo.add_chunk(
            conn,
            store,
            namespace=namespace,
            source_type=source_type,
            source_name=source_name,
            chunk_index=index,
            chunk_text=chunk,
            embedding=embedding,
            token_count=len(chunk),
        )
    return len(chunks)
