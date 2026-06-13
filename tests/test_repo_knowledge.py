"""Tests for the knowledge repository + VectorStore (Tasks 1.1, 1.6)."""

from __future__ import annotations

from app.db.repositories import knowledge
from app.db.schema import EMBEDDING_DIM


def _vec(value: float) -> list[float]:
    return [value] * EMBEDDING_DIM


def _add(conn, store, text, embedding, *, source_name="doc.txt", index=0):
    return knowledge.add_chunk(
        conn,
        store,
        source_type="file",
        source_name=source_name,
        chunk_index=index,
        chunk_text=text,
        embedding=embedding,
        metadata={"page": 1},
    )


def test_add_and_get_chunk(tmp_db, vector_store):
    chunk_id = _add(tmp_db, vector_store, "hello", _vec(0.0))
    got = knowledge.get_chunk(tmp_db, chunk_id)
    assert got is not None
    assert got["chunk_text"] == "hello"
    assert got["metadata"] == {"page": 1}  # JSON round-trips to a dict


def test_search_orders_by_distance(tmp_db, vector_store):
    near = _add(tmp_db, vector_store, "near", _vec(0.0), index=0)
    _add(tmp_db, vector_store, "far", _vec(1.0), index=1)
    results = knowledge.search(tmp_db, vector_store, _vec(0.0), k=2)
    assert [r["id"] for r in results] == [near, results[1]["id"]]
    assert results[0]["id"] == near
    assert results[0]["distance"] <= results[1]["distance"]


def test_delete_chunk_removes_vector(tmp_db, vector_store):
    chunk_id = _add(tmp_db, vector_store, "bye", _vec(0.0))
    knowledge.delete_chunk(tmp_db, vector_store, chunk_id)
    assert knowledge.get_chunk(tmp_db, chunk_id) is None
    # Vector gone too: search returns nothing.
    assert knowledge.search(tmp_db, vector_store, _vec(0.0), k=5) == []


def test_delete_by_source(tmp_db, vector_store):
    _add(tmp_db, vector_store, "a", _vec(0.0), source_name="kb.txt", index=0)
    _add(tmp_db, vector_store, "b", _vec(0.1), source_name="kb.txt", index=1)
    _add(tmp_db, vector_store, "c", _vec(0.2), source_name="other.txt", index=0)
    removed = knowledge.delete_by_source(tmp_db, vector_store, "kb.txt")
    assert removed == 2
    assert len(knowledge.list_chunks(tmp_db)) == 1
