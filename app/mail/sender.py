"""Sending: build outgoing replies, create Pilot drafts, gated auto-send.

All functions are mail-aware and must be called sequentially (Gmail/httplib2 is
not thread-safe) — from a request handler or the cycle's dispatch phase, never
inside concurrent workers. ``send_reply`` is idempotent.
"""

from __future__ import annotations

import logging
import sqlite3
from email.utils import parseaddr
from typing import Any

from app.db.repositories import emails as emails_repo
from app.db.repositories import replies as replies_repo
from app.mail.base import MailProvider
from app.mail.models import OutgoingMessage

logger = logging.getLogger(__name__)


def build_outgoing(email: dict[str, Any], reply: dict[str, Any]) -> OutgoingMessage:
    """Build a threaded reply message from an email row + its draft reply."""
    raw_sender = email.get("sender") or ""
    to = parseaddr(raw_sender)[1] or raw_sender

    subject = (email.get("subject") or "").strip()
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()

    headers = email.get("headers") or {}
    references = (headers.get("references") or "").split()
    return OutgoingMessage(
        to=to,
        subject=subject,
        body_text=reply.get("reply_text") or "",
        thread_id=email.get("thread_id"),
        in_reply_to=headers.get("message-id"),
        references=references,
    )


def create_gmail_draft(
    conn: sqlite3.Connection,
    provider: MailProvider,
    email: dict[str, Any],
    reply: dict[str, Any],
) -> str:
    """Create a native Gmail draft (Pilot safety net); store its id."""
    draft_id = provider.create_draft(build_outgoing(email, reply))
    replies_repo.update_reply(conn, reply["id"], gmail_draft_id=draft_id)
    return draft_id


def send_reply(
    conn: sqlite3.Connection,
    provider: MailProvider,
    email: dict[str, Any],
    reply: dict[str, Any],
) -> str | None:
    """Send the reply (current text), idempotently. Returns the sent id.

    No-op if the email is already ``sent``. On success marks reply + email
    ``sent`` and best-effort deletes any stale Pilot draft. Errors propagate.
    """
    if email.get("status") == "sent":
        return None
    sent_id = provider.send(build_outgoing(email, reply))
    replies_repo.update_reply(conn, reply["id"], status="sent")
    emails_repo.update_status(conn, email["id"], "sent")

    draft_id = reply.get("gmail_draft_id")
    if draft_id:
        try:
            provider.delete_draft(draft_id)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            logger.warning("could not delete stale draft for email %s", email["id"])
    return sent_id


def should_auto_send(
    email: dict[str, Any], reply: dict[str, Any] | None, settings_row: dict[str, Any]
) -> bool:
    """The Auto-send gate. Every condition must hold (default Pilot = False)."""
    if settings_row.get("reply_mode") != "auto":
        return False
    if email.get("triage_category") != "answerable":
        return False
    if reply is None or not reply.get("should_send"):
        return False
    threshold = settings_row.get("confidence_threshold", 0.75)
    confidence = reply.get("confidence")
    if confidence is None or confidence < threshold:
        return False
    keywords = (settings_row.get("auto_send_rules") or {}).get("keywords") or []
    if keywords:
        text = f"{email.get('subject', '')} {email.get('body_text', '')}".lower()
        if not any(k.lower() in text for k in keywords):
            return False
    return True


def dispatch(
    conn: sqlite3.Connection,
    provider: MailProvider,
    email_id: int,
    settings_row: dict[str, Any],
    *,
    create_drafts: bool,
) -> str:
    """For a freshly drafted email: auto-send if it qualifies, else (Pilot)
    optionally create a Gmail draft. Returns the action taken."""
    email = emails_repo.get_email(conn, email_id)
    reply = replies_repo.get_latest_for_email(conn, email_id)
    if email is None or reply is None:
        return "none"
    if should_auto_send(email, reply, settings_row):
        send_reply(conn, provider, email, reply)
        return "sent"
    if create_drafts:
        create_gmail_draft(conn, provider, email, reply)
    return "drafted"
