"""Tests for the provider abstraction (Task 0.6)."""

from __future__ import annotations

from app.providers.base import EmbeddingProvider, LLMProvider
from app.providers.openai_provider import OpenAIProvider


def test_fake_provider_satisfies_interface(fake_provider):
    assert isinstance(fake_provider, EmbeddingProvider)
    assert isinstance(fake_provider, LLMProvider)
    vecs = fake_provider.embed(["a", "bb"])
    assert len(vecs) == 2
    assert fake_provider.generate("sys", "user") == "fake reply"


def test_openai_provider_is_import_safe_without_network():
    # Constructing the provider must not create a client or hit the network.
    provider = OpenAIProvider(
        api_key="sk-not-real",
        embedding_model="text-embedding-3-small",
        generation_model="gpt-4o-mini",
    )
    assert provider._client is None
    assert isinstance(provider, EmbeddingProvider)
    assert isinstance(provider, LLMProvider)
