"""Grounded reply generation with structured output.

The model is instructed to answer **only** from the retrieved chunks and defer
when they're insufficient. ``sources_used`` is taken from the chunks we actually
supplied (not the model's claim). Malformed output yields an empty reply so the
pipeline can route to a human.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import LLMProvider
from app.rag.retrieval import RetrievedChunk


@dataclass(frozen=True)
class GenerationResult:
    reply: str
    sources_used: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    should_send: bool = False


GENERATE_SYSTEM = (
    "You draft email replies for an assistant. Use ONLY the provided context "
    "snippets to answer; do not invent facts. If the context is insufficient to "
    "answer confidently, say so and defer to a human. Return JSON: "
    "{\"reply\": ..., \"confidence\": 0..1, \"should_send\": true|false}."
)

GENERATE_SCHEMA = {
    "name": "reply",
    "schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "confidence": {"type": "number"},
            "should_send": {"type": "boolean"},
        },
        "required": ["reply", "confidence", "should_send"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _format_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no context available)"
    return "\n\n".join(
        f"[{i + 1}] (source: {c.source_name}, score: {c.score:.2f})\n{c.text}"
        for i, c in enumerate(chunks)
    )


def _build_user(email: dict[str, Any], chunks, thread_text: str) -> str:
    parts = ["CONTEXT:", _format_context(chunks)]
    if thread_text:
        parts += ["\nCONVERSATION SO FAR:", thread_text]
    parts += [
        "\nEMAIL TO ANSWER:",
        f"From: {email.get('sender', '')}",
        f"Subject: {email.get('subject', '')}",
        "",
        email.get("body_text", ""),
    ]
    return "\n".join(parts)


def generate_reply(
    provider: LLMProvider,
    email: dict[str, Any],
    chunks: list[RetrievedChunk],
    *,
    thread_text: str = "",
) -> GenerationResult:
    """Draft a grounded reply; sources come from the supplied chunks."""
    sources = [
        {"chunk_id": c.chunk_id, "source_name": c.source_name, "score": c.score}
        for c in chunks
    ]
    raw = provider.generate(
        GENERATE_SYSTEM,
        _build_user(email, chunks, thread_text),
        json_schema=GENERATE_SCHEMA,
    )
    try:
        data = json.loads(raw)
        return GenerationResult(
            reply=str(data["reply"]),
            sources_used=sources,
            confidence=float(data.get("confidence", 0.0)),
            should_send=bool(data.get("should_send", False)),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        # Fail safe: empty reply → pipeline routes to a human.
        return GenerationResult(reply="", sources_used=sources)
