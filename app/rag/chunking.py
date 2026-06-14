"""Split text into overlapping character windows for embedding."""

from __future__ import annotations


def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    """Split ``text`` into chunks of ~``size`` chars overlapping by ``overlap``.

    Whitespace-only chunks are dropped; each chunk is stripped. Short text
    yields a single chunk. ``overlap`` must be smaller than ``size``.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be >= 0 and < size")

    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= size:
        return [normalized]

    step = size - overlap
    chunks: list[str] = []
    for start in range(0, len(normalized), step):
        piece = normalized[start : start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= len(normalized):
            break
    return chunks
