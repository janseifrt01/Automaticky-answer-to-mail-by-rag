"""LLM triage: classify an email into a reply disposition.

Category is an **open string** (stored as TEXT): the enum is the MVP's known
set, but a future multi-stream epic can add stream names without a schema
change. Malformed model output fails safe to ``needs_human``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.providers.base import LLMProvider


class TriageCategory(str, Enum):
    ANSWERABLE = "answerable"  # attempt a KB-grounded reply
    NEEDS_HUMAN = "needs_human"  # route to a person
    NO_REPLY = "no_reply"  # newsletters, receipts, automated mail


@dataclass(frozen=True)
class TriageResult:
    category: str  # one of TriageCategory today; open for future stream names
    reason: str


_KNOWN = {c.value for c in TriageCategory}

TRIAGE_SYSTEM = (
    "You triage incoming email for an assistant that answers from a knowledge "
    "base. Classify the email into exactly one category: "
    "'answerable' (a factual question likely answerable from a knowledge base), "
    "'needs_human' (complex, sensitive, or requires a person), or "
    "'no_reply' (newsletters, receipts, notifications, automated mail). "
    "Respond with JSON: {\"category\": ..., \"reason\": ...}."
)

TRIAGE_SCHEMA = {
    "name": "triage",
    "schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(_KNOWN)},
            "reason": {"type": "string"},
        },
        "required": ["category", "reason"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _format_email(email: dict[str, Any]) -> str:
    return (
        f"From: {email.get('sender', '')}\n"
        f"Subject: {email.get('subject', '')}\n\n"
        f"{email.get('body_text', '')}"
    )


def _parse(raw: str) -> TriageResult:
    try:
        data = json.loads(raw)
        category = str(data["category"])
        if category not in _KNOWN:
            return TriageResult(TriageCategory.NEEDS_HUMAN.value, "unknown category")
        return TriageResult(category, str(data.get("reason", "")))
    except (json.JSONDecodeError, KeyError, TypeError):
        return TriageResult(
            TriageCategory.NEEDS_HUMAN.value, "unparseable triage output"
        )


def classify(provider: LLMProvider, email: dict[str, Any]) -> TriageResult:
    """Classify ``email`` via the LLM; fail safe to needs_human on bad output."""
    raw = provider.generate(
        TRIAGE_SYSTEM, _format_email(email), json_schema=TRIAGE_SCHEMA
    )
    return _parse(raw)
