"""The ``VectorStore`` interface.

Callers depend only on this protocol, so the backing implementation
(``sqlite-vec`` now, ``pgvector`` later) can change without touching the
repositories that use it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    """Stores embeddings keyed by knowledge-chunk id and runs KNN search."""

    def add(self, chunk_id: int, embedding: list[float]) -> None:
        """Insert (or replace) the embedding for ``chunk_id``."""
        ...

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        """Return up to ``k`` ``(chunk_id, distance)`` pairs, nearest first."""
        ...

    def delete(self, chunk_id: int) -> None:
        """Remove the embedding for ``chunk_id`` (no-op if absent)."""
        ...
