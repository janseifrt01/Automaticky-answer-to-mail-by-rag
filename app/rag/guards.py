"""Rule-based safe-sender / loop guards.

Operates on the headers Epic 2 surfaces (lowercased keys). Runs before any LLM
call to cheaply reject mail we must never auto-reply to (automated senders,
mailing lists, our own mail). Returns a ``no_reply`` :class:`TriageResult` when a
guard trips, else ``None``.
"""

from __future__ import annotations

import re
from typing import Any

from app.rag.triage import TriageCategory, TriageResult

_NO_REPLY_SENDER = re.compile(r"no[-_.]?reply|do[-_.]?not[-_.]?reply", re.IGNORECASE)
_BULK_PRECEDENCE = {"bulk", "list", "junk"}


def check_guards(
    email: dict[str, Any], *, account_email: str | None = None
) -> TriageResult | None:
    """Return a ``no_reply`` result if a safe-sender guard trips, else ``None``."""
    headers = email.get("headers") or {}
    sender = (email.get("sender") or "").lower()

    auto = headers.get("auto-submitted")
    if auto and auto.strip().lower() != "no":
        return TriageResult(TriageCategory.NO_REPLY.value, "auto-submitted header")

    if "list-id" in headers:
        return TriageResult(TriageCategory.NO_REPLY.value, "mailing list (List-Id)")

    precedence = (headers.get("precedence") or "").strip().lower()
    if precedence in _BULK_PRECEDENCE:
        return TriageResult(
            TriageCategory.NO_REPLY.value, f"precedence: {precedence}"
        )

    if account_email and account_email.lower() in sender:
        return TriageResult(TriageCategory.NO_REPLY.value, "our own mail")

    if _NO_REPLY_SENDER.search(sender):
        return TriageResult(TriageCategory.NO_REPLY.value, "no-reply sender")

    return None
