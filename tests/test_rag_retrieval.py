"""Tests for retrieval (Task 4.3)."""

from __future__ import annotations

from app.rag.ingest import ingest_text
from app.rag.retrieval import RetrievedChunk, retrieve


def test_retrieve_returns_scored_chunks(tmp_db, vector_store, fake_provider):
    ingest_text(
        tmp_db,
        vector_store,
        fake_provider,
        source_type="paste",
        source_name="kb",
        text="abcdefghij" * 30,
        chunk_size=100,
        chunk_overlap=20,
    )
    results = retrieve(tmp_db, vector_store, fake_provider, "query text", k=3)
    assert results and all(isinstance(r, RetrievedChunk) for r in results)
    assert all(0.0 <= r.score <= 1.0 for r in results)
    # Returned nearest-first → non-increasing scores.
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_empty_kb_returns_nothing(tmp_db, vector_store, fake_provider):
    assert retrieve(tmp_db, vector_store, fake_provider, "q", k=5) == []
