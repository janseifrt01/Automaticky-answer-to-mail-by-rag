"""Provider protocols for embeddings and text generation."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class CompositeProvider:
    """Pairs an embedding source with a (possibly different) generation source.

    Lets the app draft with one provider (e.g. Anthropic Claude) while embeddings
    come from another (e.g. OpenAI), since not every LLM offers an embeddings API.
    """

    embedder: EmbeddingProvider
    llm: LLMProvider

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embedder.embed(texts)

    def generate(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
    ) -> str:
        return self.llm.generate(system, user, json_schema=json_schema)
