"""Tests for grounded generation (Task 4.5)."""

from __future__ import annotations

from app.rag.generate import generate_reply
from app.rag.retrieval import RetrievedChunk

from tests.conftest import ScriptedProvider

EMAIL = {"sender": "a@x.com", "subject": "Hours", "body_text": "When open?"}
CHUNKS = [
    RetrievedChunk(
        chunk_id=1, source_name="faq", text="We open at 9am.", score=0.9, distance=0.2
    ),
]


def test_parses_structured_output():
    provider = ScriptedProvider(
        ['{"reply": "We open at 9am.", "confidence": 0.92, "should_send": true}']
    )
    result = generate_reply(provider, EMAIL, CHUNKS)
    assert result.reply == "We open at 9am."
    assert result.confidence == 0.92
    assert result.should_send is True
    # Sources come from the supplied chunks, not the model.
    assert result.sources_used == [
        {"chunk_id": 1, "source_name": "faq", "score": 0.9}
    ]


def test_context_and_thread_in_prompt():
    provider = ScriptedProvider(
        ['{"reply": "hi", "confidence": 0.5, "should_send": false}']
    )
    generate_reply(provider, EMAIL, CHUNKS, thread_text="Earlier: hello")
    _system, user = provider.calls[0]
    assert "We open at 9am." in user  # context chunk
    assert "Earlier: hello" in user  # thread context
    assert "When open?" in user  # the email


def test_malformed_output_yields_empty_reply():
    provider = ScriptedProvider(["totally not json"])
    result = generate_reply(provider, EMAIL, CHUNKS)
    assert result.reply == ""
    assert result.should_send is False
    assert result.sources_used  # sources still attached
