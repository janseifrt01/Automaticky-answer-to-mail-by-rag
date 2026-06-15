"""Provider selection.

Two independently selectable concerns, both defaulting to OpenAI:

* embeddings — "openai" | "github_models"  (Anthropic has no embeddings API)
* generation — "openai" | "anthropic" | "github_models"

The active choice persists in the DB settings row and is resolved per cycle via
``get_provider_for``; env supplies the defaults plus secrets and model names.
Built providers are cached by selection, so switching is a cheap, reversible toggle.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.anthropic_provider import build_anthropic_provider
from app.providers.base import (
    CompositeProvider,
    EmbeddingProvider,
    LLMProvider,
    Provider,
)
from app.providers.fastembed_provider import build_fastembed_provider
from app.providers.openai_provider import (
    build_github_models_provider,
    build_openai_provider,
)

OPENAI = "openai"
ANTHROPIC = "anthropic"
GITHUB_MODELS = "github_models"
FASTEMBED = "fastembed"

# Output dimension per local fastembed model (the ones we document / expose).
_FASTEMBED_DIMS = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "intfloat/multilingual-e5-large": 1024,
}
_DEFAULT_FASTEMBED_DIM = 384
_OPENAI_DIM = 1536  # text-embedding-3-small; GitHub Models passes it through


def _build_embedder(settings: Settings, kind: str) -> EmbeddingProvider:
    if kind == FASTEMBED:
        return build_fastembed_provider(settings)
    if kind == GITHUB_MODELS:
        return build_github_models_provider(settings)
    return build_openai_provider(settings)  # OpenAI is the default embedder


def _build_llm(
    settings: Settings, kind: str, generation_model: str | None
) -> LLMProvider:
    if kind == ANTHROPIC:
        return build_anthropic_provider(settings, generation_model=generation_model)
    if kind == GITHUB_MODELS:
        return build_github_models_provider(
            settings, generation_model=generation_model
        )
    return build_openai_provider(settings, generation_model=generation_model)


def build_provider(
    settings: Settings,
    *,
    llm_kind: str = OPENAI,
    embedding_kind: str = OPENAI,
    generation_model: str | None = None,
) -> Provider:
    """Compose an embedding source with a generation source."""
    return CompositeProvider(
        embedder=_build_embedder(settings, embedding_kind),
        llm=_build_llm(settings, llm_kind, generation_model),
    )


@lru_cache
def get_provider(
    llm_kind: str = OPENAI,
    embedding_kind: str = OPENAI,
    generation_model: str | None = None,
) -> Provider:
    """Return the cached provider for a given selection (built from app settings)."""
    return build_provider(
        get_settings(),
        llm_kind=llm_kind,
        embedding_kind=embedding_kind,
        generation_model=generation_model,
    )


def get_provider_for(settings_row: dict) -> Provider:
    """Resolve the provider from a DB settings row, falling back to env defaults."""
    settings = get_settings()
    llm_kind = (settings_row.get("llm_provider") or settings.llm_provider).strip()
    embedding_kind = (
        settings_row.get("embedding_provider") or settings.embedding_provider
    ).strip()
    generation_model = (settings_row.get("generation_model") or "").strip() or None
    return get_provider(llm_kind, embedding_kind, generation_model)


def expected_embedding_dim(settings_row: dict) -> int:
    """Embedding dimension implied by the selected embedding provider/model.

    Used to size the vector table and to detect when a re-index is needed.
    """
    settings = get_settings()
    kind = (
        settings_row.get("embedding_provider") or settings.embedding_provider
    ).strip()
    if kind == FASTEMBED:
        return _FASTEMBED_DIMS.get(settings.fastembed_model, _DEFAULT_FASTEMBED_DIM)
    return _OPENAI_DIM
