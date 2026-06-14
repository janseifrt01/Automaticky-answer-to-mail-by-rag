"""Tests for the ingest service (Task 3.3)."""

from __future__ import annotations

from app.db.repositories import knowledge as kb_repo
from app.rag.ingest import ingest_text


def test_ingest_stores_chunks_and_vectors(tmp_db, vector_store, fake_provider):
    text = "abcdefghij" * 30  # 300 chars
    n = ingest_text(
        tmp_db,
        vector_store,
        fake_provider,
        source_type="paste",
        source_name="doc",
        text=text,
        chunk_size=100,
        chunk_overlap=20,
    )
    assert n > 1
    assert len(kb_repo.list_chunks(tmp_db, source_name="doc")) == n
    # Vectors are searchable.
    query = fake_provider.embed(["q"])[0]
    assert len(kb_repo.search(tmp_db, vector_store, query, k=n)) == n


def test_reingest_replaces_previous_version(tmp_db, vector_store, fake_provider):
    common = dict(
        source_type="paste", source_name="doc", chunk_size=100, chunk_overlap=20
    )
    ingest_text(tmp_db, vector_store, fake_provider, text="x" * 300, **common)
    # Re-ingest a shorter doc under the same source name.
    ingest_text(tmp_db, vector_store, fake_provider, text="y" * 50, **common)
    chunks = kb_repo.list_chunks(tmp_db, source_name="doc")
    assert len(chunks) == 1  # old chunks replaced, not appended
    assert chunks[0]["chunk_text"] == "y" * 50


def test_namespace_isolation(tmp_db, vector_store, fake_provider):
    ingest_text(
        tmp_db,
        vector_store,
        fake_provider,
        source_type="paste",
        source_name="offer-doc",
        text="offer terms",
        namespace="offers",
    )
    query = fake_provider.embed(["q"])[0]
    # Chunk is only visible within its namespace.
    assert kb_repo.search(tmp_db, vector_store, query, k=5, namespace="offers")
    assert kb_repo.search(tmp_db, vector_store, query, k=5, namespace="default") == []


def test_empty_text_stores_nothing(tmp_db, vector_store, fake_provider):
    n = ingest_text(
        tmp_db,
        vector_store,
        fake_provider,
        source_type="paste",
        source_name="empty",
        text="   ",
    )
    assert n == 0
    assert kb_repo.list_chunks(tmp_db, source_name="empty") == []
