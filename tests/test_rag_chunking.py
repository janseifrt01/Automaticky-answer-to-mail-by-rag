"""Tests for chunking (Task 3.2)."""

from __future__ import annotations

import pytest
from app.rag.chunking import chunk_text


def test_short_text_is_single_chunk():
    assert chunk_text("hello", size=100, overlap=10) == ["hello"]


def test_empty_text_yields_no_chunks():
    assert chunk_text("   ", size=100, overlap=10) == []


def test_long_text_splits_with_overlap():
    text = "abcdefghij" * 3  # 30 chars
    chunks = chunk_text(text, size=10, overlap=4)
    # step = 6 → starts at 0,6,12,18,24 → 5 chunks
    assert len(chunks) == 5
    assert chunks[0] == text[0:10]
    # overlap: end of chunk0 and start of chunk1 share 4 chars
    assert chunks[0][-4:] == chunks[1][:4]


def test_invalid_overlap_raises():
    with pytest.raises(ValueError):
        chunk_text("x" * 50, size=10, overlap=10)
