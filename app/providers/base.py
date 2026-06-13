"""Provider protocols for embeddings and text generation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into embedding vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text (order preserved)."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Generates text from a system + user prompt."""

    def generate(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
    ) -> str:
        """Return the model's text response.

        When ``json_schema`` is provided, the implementation should request a
        structured JSON response conforming to that schema.
        """
        ...


@runtime_checkable
class Provider(EmbeddingProvider, LLMProvider, Protocol):
    """A provider that offers both embeddings and generation."""
