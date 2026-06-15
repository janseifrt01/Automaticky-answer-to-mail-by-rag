"""Local embeddings (fastembed) + vector-table dimension + reindex.

Fully offline: fastembed is never loaded (the provider is lazy), and reindex is
exercised with deterministic fake embedders.
"""

from __future__ import annotations

from app.db.repositories import knowledge as kb_repo
from app.db.schema import recreate_vector_table, vector_table_dim
from app.providers.base import CompositeProvider, EmbeddingProvider
from app.providers.factory import (
    expected_embedding_dim,
    get_provider,
    get_provider_for,
)
from app.providers.fastembed_provider import FastEmbedProvider
from app.providers.openai_provider import OpenAIProvider
from app.rag import ingest, reindex


def test_fastembed_provider_is_lazy_and_import_safe():
    provider = FastEmbedProvider(model_name="BAAI/bge-small-en-v1.5")
    assert provider._model is None  # no model download on construction
    assert isinstance(provider, EmbeddingProvider)


def test_expected_embedding_dim_by_provider():
    assert expected_embedding_dim({"embedding_provider": "openai"}) == 1536
    assert expected_embedding_dim({"embedding_provider": "github_models"}) == 1536
    assert expected_embedding_dim({"embedding_provider": "fastembed"}) == 384


def test_get_provider_for_pairs_fastembed_with_openai_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from app.config import get_settings

    get_settings.cache_clear()
    get_provider.cache_clear()
    try:
        provider = get_provider_for(
            {"llm_provider": "openai", "embedding_provider": "fastembed"}
        )
        assert isinstance(provider, CompositeProvider)
        assert isinstance(provider.embedder, FastEmbedProvider)
        assert isinstance(provider.llm, OpenAIProvider)
    finally:
        get_settings.cache_clear()
        get_provider.cache_clear()


def test_vector_table_dim_default(tmp_db):
    assert vector_table_dim(tmp_db) == 1536


def test_recreate_vector_table_changes_dim(tmp_db):
    recreate_vector_table(tmp_db, 384)
    assert vector_table_dim(tmp_db) == 384


class _Dim8Embedder:
    """Offline embedder producing deterministic 8-dim vectors."""

    def embed(self, texts):
        return [[float((len(t) + i) % 5) for i in range(8)] for t in texts]


def test_reindex_rebuilds_at_new_dimension(tmp_db, vector_store, fake_provider):
    # Ingest at 1536-dim (FakeProvider) into the default 1536 table.
    ingest.ingest_text(
        tmp_db,
        vector_store,
        fake_provider,
        source_type="paste",
        source_name="faq",
        text="hello world from the knowledge base",
        chunk_size=1000,
        chunk_overlap=0,
    )
    assert vector_table_dim(tmp_db) == 1536

    # Reindex with an 8-dim embedder: table is recreated, chunks re-embedded.
    count, dim = reindex.reindex_all(tmp_db, vector_store, _Dim8Embedder())
    assert dim == 8
    assert count >= 1
    assert vector_table_dim(tmp_db) == 8

    # Search now works in the new 8-dim space.
    hits = kb_repo.search(tmp_db, vector_store, [1.0] * 8, k=3)
    assert hits
