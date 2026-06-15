"""Local embeddings via fastembed (ONNX runtime, no torch).

Embedding only — paired with a generation provider through
:class:`CompositeProvider`. Import-safe without fastembed installed and without a
model download: the model is loaded lazily on the first ``embed`` call (which
downloads it to a local cache once).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class FastEmbedProvider:
    """Embeds text with a local fastembed model (e.g. BAAI/bge-small-en-v1.5)."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: TextEmbedding | None = None

    @property
    def model(self) -> TextEmbedding:
        """Lazily load the model on first use (downloads to a local cache once)."""
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self.model.embed(list(texts))]


def build_fastembed_provider(settings) -> FastEmbedProvider:
    """Construct a :class:`FastEmbedProvider` from app settings."""
    return FastEmbedProvider(model_name=settings.fastembed_model)


__all__ = ["FastEmbedProvider", "build_fastembed_provider"]
