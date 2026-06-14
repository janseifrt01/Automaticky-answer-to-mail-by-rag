"""Tests for scoring + confidence gate (Task 4.0)."""

from __future__ import annotations

from app.rag.scoring import distance_to_score, passes_gate


def test_zero_distance_is_perfect_score():
    assert distance_to_score(0.0) == 1.0


def test_known_distance_maps_to_cosine():
    # Unit vectors with L2 distance 1 → cosine 0.5.
    assert distance_to_score(1.0) == 0.5


def test_distant_vectors_clamp_to_zero():
    # Opposite unit vectors (d=2) → cosine -1, clamped to 0.
    assert distance_to_score(2.0) == 0.0


def test_larger_distance_lowers_score():
    assert distance_to_score(0.2) > distance_to_score(0.8)


def test_gate():
    assert passes_gate(0.8, 0.75) is True
    assert passes_gate(0.7, 0.75) is False
