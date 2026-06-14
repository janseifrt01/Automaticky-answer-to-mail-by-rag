"""Retrieval: embed a query and return scored knowledge chunks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.db.repositories import knowledge as kb_repo
from app.db.vector_store.base import VectorStore
from app.providers.base import EmbeddingProvider
from app.rag.scoring import distance_to_score


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    source_name: str
    text: str
    score: float  # cosine similarity in [0, 1]
    distance: float  # raw L2 from sqlite-vec


def retrieve(
    conn: sqlite3.Connection,
    store: VectorStore,
    provider: EmbeddingProvider,
    query_text: str,
    k: int,
    *,
    namespace: str = "default",
) -> list[RetrievedChunk]:
    """Embed ``query_text`` and return up to ``k`` chunks, nearest first."""
    embedding = provider.embed([query_text])[0]
    hits = kb_repo.search(conn, store, embedding, k, namespace=namespace)
    return [
        RetrievedChunk(
            chunk_id=h["id"],
            source_name=h["source_name"],
            text=h["chunk_text"],
            distance=h["distance"],
            score=distance_to_score(h["distance"]),
        )
        for h in hits
    ]
