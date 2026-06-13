"""AI provider abstraction (embeddings + generation).

Keeps a single ``embed()`` / ``generate()`` interface so the OpenAI default
can be swapped for another provider via config without touching callers.
"""

from app.providers.base import EmbeddingProvider, LLMProvider
from app.providers.factory import get_provider

__all__ = ["EmbeddingProvider", "LLMProvider", "get_provider"]
