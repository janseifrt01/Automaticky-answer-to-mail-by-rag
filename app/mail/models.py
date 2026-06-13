"""Provider-agnostic mail domain models.

These are the only mail types that cross the :class:`MailProvider` boundary —
no Gmail (or other provider) structures leak to callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmailMessage:
    """A received email, normalized across providers."""

    provider_message_id: str  # provider's id for this message
    thread_id: str | None  # provider's conversation/thread id
    rfc_message_id: str | None  # RFC 5322 Message-ID header (threading)
    sender: str
    recipients: list[str]
    subject: str
    body_text: str  # plaintext (HTML stripped when no text/plain part)
    headers: dict[str, str]  # selected headers, lowercased keys
    received_at: str | None  # ISO-8601 UTC


@dataclass
class OutgoingMessage:
    """An email to create as a draft or send."""

    to: str
    subject: str
    body_text: str
    thread_id: str | None = None  # reply within this provider thread
    in_reply_to: str | None = None  # RFC Message-ID being answered
    references: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of an incremental receive."""

    messages: list[EmailMessage]
    cursor: str  # new opaque cursor to persist
    full_sync: bool = False  # True if the prior cursor expired → full resync
