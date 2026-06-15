"""Tests for the provider abstraction (Task 0.6)."""

from __future__ import annotations

from types import SimpleNamespace

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import (
    CompositeProvider,
    EmbeddingProvider,
    LLMProvider,
    Provider,
)
from app.providers.factory import get_provider, get_provider_for
from app.providers.openai_provider import (
    OpenAIProvider,
    build_github_models_provider,
)


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


class _RecordingAnthropicClient:
    """Fake Anthropic client capturing the create() kwargs (offline)."""

    def __init__(self, text: str) -> None:
        self.kwargs: dict = {}
        block = SimpleNamespace(type="text", text=text)
        self._resp = SimpleNamespace(content=[block])
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return self._resp


def test_composite_provider_delegates():
    class Embedder:
        def embed(self, texts):
            return [[1.0] for _ in texts]

    class LLM:
        def generate(self, system, user, *, json_schema=None):
            return f"{system}|{user}"

    composite = CompositeProvider(embedder=Embedder(), llm=LLM())
    assert composite.embed(["a", "b"]) == [[1.0], [1.0]]
    assert composite.generate("sys", "usr") == "sys|usr"
    assert isinstance(composite, Provider)


def test_anthropic_provider_is_import_safe_without_network():
    provider = AnthropicProvider(
        api_key="sk-not-real", generation_model="claude-haiku-4-5"
    )
    assert provider._client is None
    assert isinstance(provider, LLMProvider)


def test_anthropic_provider_maps_json_schema_and_joins_text():
    provider = AnthropicProvider(api_key="x", generation_model="claude-haiku-4-5")
    fake = _RecordingAnthropicClient('{"reply": "hi"}')
    provider._client = fake  # inject; the client property returns it when set
    schema = {"name": "reply", "schema": {"type": "object"}, "strict": True}
    out = provider.generate("sys", "usr", json_schema=schema)
    assert out == '{"reply": "hi"}'
    assert fake.kwargs["model"] == "claude-haiku-4-5"
    assert fake.kwargs["system"] == "sys"
    # The OpenAI-style wrapper is unwrapped to the bare JSON Schema.
    assert fake.kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": {"type": "object"}}
    }


def test_github_models_builder_uses_base_url():
    settings = SimpleNamespace(
        github_token="ghp_x",
        github_models_base_url="https://models.github.ai/inference",
        github_models_generation_model="openai/gpt-4o-mini",
        github_models_embedding_model="openai/text-embedding-3-small",
    )
    provider = build_github_models_provider(settings)
    assert provider._base_url == "https://models.github.ai/inference"
    assert provider._generation_model == "openai/gpt-4o-mini"
    assert provider._embedding_model == "openai/text-embedding-3-small"


def test_get_provider_for_pairs_anthropic_llm_with_openai_embedder(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from app.config import get_settings

    get_settings.cache_clear()
    get_provider.cache_clear()
    try:
        provider = get_provider_for(
            {"llm_provider": "anthropic", "embedding_provider": "openai"}
        )
        assert isinstance(provider, CompositeProvider)
        assert isinstance(provider.llm, AnthropicProvider)
        assert isinstance(provider.embedder, OpenAIProvider)
    finally:
        get_settings.cache_clear()
        get_provider.cache_clear()
