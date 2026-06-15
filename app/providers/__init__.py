"""AI provider abstraction (embeddings + generation).

Keeps a single ``embed()`` / ``generate()`` interface so providers (OpenAI,
Anthropic, GitHub Models) can be swapped via settings without touching callers.
The embedding and generation sources are selected independently (see
``CompositeProvider``), because not every LLM offers an embeddings API.
"""

from app.providers.base import (
    CompositeProvider,
    EmbeddingProvider,
    LLMProvider,
    Provider,
)
from app.providers.factory import get_provider, get_provider_for

__all__ = [
    "EmbeddingProvider",
    "LLMProvider",
    "Provider",
    "CompositeProvider",
    "get_provider",
    "get_provider_for",
]
