"""Tests for LLM triage (Task 4.2)."""

from __future__ import annotations

from app.rag.triage import TriageCategory, classify

from tests.conftest import ScriptedProvider

EMAIL = {"sender": "a@x.com", "subject": "Q", "body_text": "When do you open?"}


def test_parses_valid_category():
    provider = ScriptedProvider(['{"category": "answerable", "reason": "a question"}'])
    result = classify(provider, EMAIL)
    assert result.category == TriageCategory.ANSWERABLE.value
    assert result.reason == "a question"


def test_unknown_category_defaults_to_needs_human():
    provider = ScriptedProvider(['{"category": "weird", "reason": "x"}'])
    assert classify(provider, EMAIL).category == TriageCategory.NEEDS_HUMAN.value


def test_malformed_output_defaults_to_needs_human():
    provider = ScriptedProvider(["not json at all"])
    assert classify(provider, EMAIL).category == TriageCategory.NEEDS_HUMAN.value


def test_email_content_passed_to_model():
    provider = ScriptedProvider(['{"category": "no_reply", "reason": "newsletter"}'])
    classify(provider, EMAIL)
    _system, user = provider.calls[0]
    assert "When do you open?" in user
