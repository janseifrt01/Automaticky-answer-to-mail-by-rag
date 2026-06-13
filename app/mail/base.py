"""The ``MailProvider`` facade for receiving and sending mail.

Callers depend only on this protocol and the domain models, so a future
Outlook/IMAP provider is a new implementation, not a rewrite.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.mail.models import EmailMessage, OutgoingMessage, SyncResult


@runtime_checkable
class MailProvider(Protocol):
    """Provider-agnostic interface for a single mailbox."""

    # --- identity / connection ---
    def is_connected(self) -> bool:
        """Whether a mailbox is connected and usable."""
        ...

    def account_email(self) -> str | None:
        """The connected account's email address, if known."""
        ...

    # --- receiving ---
    def fetch_new(self, cursor: str | None) -> SyncResult:
        """Fetch messages added since ``cursor``; return them + a new cursor.

        ``cursor`` is opaque to callers. A ``None`` or expired cursor triggers
        a bounded full sync (``SyncResult.full_sync == True``).
        """
        ...

    def get_message(self, message_id: str) -> EmailMessage:
        """Fetch a single message by its provider id."""
        ...

    def get_thread(self, thread_id: str) -> list[EmailMessage]:
        """Fetch all messages in a thread, oldest first."""
        ...

    # --- sending ---
    def create_draft(self, message: OutgoingMessage) -> str:
        """Create a draft; return the provider's draft id."""
        ...

    def send(self, message: OutgoingMessage) -> str:
        """Send a message; return the provider's sent-message id."""
        ...

    def send_draft(self, draft_id: str) -> str:
        """Send a previously created draft; return the sent-message id."""
        ...
