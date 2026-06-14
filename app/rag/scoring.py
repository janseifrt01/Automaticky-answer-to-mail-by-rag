"""Shared retrieval scoring — the seam between ingestion and the pipeline.

`sqlite-vec` returns **L2 distance**. OpenAI embeddings are unit-normalized, so
cosine similarity is ``1 - distance²/2``. This module is the single owner of the
distance↔score conversion and the confidence gate, used by retrieval and the UI.
"""

from __future__ import annotations


def distance_to_score(distance: float) -> float:
    """Convert an L2 distance (unit vectors) to cosine similarity in [0, 1]."""
    score = 1.0 - (distance * distance) / 2.0
    return max(0.0, min(1.0, score))


def passes_gate(top_score: float, threshold: float) -> bool:
    """Whether the best retrieval score clears the confidence threshold."""
    return top_score >= threshold
