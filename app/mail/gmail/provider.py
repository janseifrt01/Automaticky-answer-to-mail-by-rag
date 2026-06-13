"""``GmailProvider`` — maps the Gmail API to the :class:`MailProvider` facade."""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from email.message import EmailMessage as MIMEMessage

from googleapiclient.errors import HttpError

from app.mail.gmail.client import GmailClient
from app.mail.models import EmailMessage, OutgoingMessage, SyncResult

# Headers surfaced to callers (lowercased). Includes the safe-sender markers
# that Epic 4 interprets.
_KEPT_HEADERS = {
    "from",
    "to",
    "cc",
    "subject",
    "date",
    "message-id",
    "in-reply-to",
    "references",
    "list-id",
    "auto-submitted",
    "precedence",
}
# Cap a full sync so a huge mailbox can't stall the first run.
_FULL_SYNC_MAX_PAGES = 1


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _walk_parts(payload: dict) -> tuple[str | None, str | None]:
    """Return ``(plain_text, html)`` found anywhere in the MIME tree."""
    plain: str | None = None
    html: str | None = None
    stack = [payload]
    while stack:
        part = stack.pop()
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            decoded = _b64url_decode(data).decode("utf-8", errors="replace")
            if mime == "text/plain" and plain is None:
                plain = decoded
            elif mime == "text/html" and html is None:
                html = decoded
        stack.extend(part.get("parts", []) or [])
    return plain, html


def _internal_date_to_iso(internal_date: str | None) -> str | None:
    if not internal_date:
        return None
    return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC).isoformat()


def gmail_message_to_domain(msg: dict) -> EmailMessage:
    """Map a Gmail ``users.messages.get`` payload to an :class:`EmailMessage`."""
    payload = msg.get("payload", {})
    raw_headers = {
        h["name"].lower(): h["value"] for h in payload.get("headers", [])
    }
    headers = {k: v for k, v in raw_headers.items() if k in _KEPT_HEADERS}

    plain, html = _walk_parts(payload)
    body_text = plain if plain is not None else (_strip_html(html) if html else "")

    recipients = [
        r.strip() for r in raw_headers.get("to", "").split(",") if r.strip()
    ]
    return EmailMessage(
        provider_message_id=msg["id"],
        thread_id=msg.get("threadId"),
        rfc_message_id=raw_headers.get("message-id"),
        sender=raw_headers.get("from", ""),
        recipients=recipients,
        subject=raw_headers.get("subject", ""),
        body_text=body_text,
        headers=headers,
        received_at=_internal_date_to_iso(msg.get("internalDate")),
    )


def _build_raw(message: OutgoingMessage) -> str:
    mime = MIMEMessage()
    mime["To"] = message.to
    mime["Subject"] = message.subject
    if message.in_reply_to:
        mime["In-Reply-To"] = message.in_reply_to
    refs = list(message.references)
    if message.in_reply_to and message.in_reply_to not in refs:
        refs.append(message.in_reply_to)
    if refs:
        mime["References"] = " ".join(refs)
    mime.set_content(message.body_text)
    return base64.urlsafe_b64encode(mime.as_bytes()).decode()


class GmailProvider:
    """Gmail implementation of :class:`MailProvider`.

    Takes a :class:`GmailClient` (``None`` when not connected) and the connected
    account's email. ``account_email`` is read from stored settings, so it
    needs no network call.
    """

    def __init__(
        self, client: GmailClient | None, account_email: str | None = None
    ) -> None:
        self._client = client
        self._account_email = account_email

    # --- identity / connection ---
    def is_connected(self) -> bool:
        return self._client is not None

    def account_email(self) -> str | None:
        return self._account_email

    def _require_client(self) -> GmailClient:
        if self._client is None:
            raise RuntimeError("Gmail is not connected")
        return self._client

    # --- receiving ---
    def get_message(self, message_id: str) -> EmailMessage:
        return gmail_message_to_domain(self._require_client().get_message(message_id))

    def get_thread(self, thread_id: str) -> list[EmailMessage]:
        thread = self._require_client().get_thread(thread_id)
        return [gmail_message_to_domain(m) for m in thread.get("messages", [])]

    def fetch_new(self, cursor: str | None) -> SyncResult:
        client = self._require_client()
        if cursor is None:
            return self._full_sync(client)
        try:
            return self._incremental_sync(client, cursor)
        except HttpError as exc:
            if int(getattr(exc.resp, "status", 0) or 0) == 404:
                # historyId expired → bounded full resync.
                result = self._full_sync(client)
                return SyncResult(result.messages, result.cursor, full_sync=True)
            raise

    def _full_sync(self, client: GmailClient) -> SyncResult:
        ids: list[str] = []
        page_token: str | None = None
        for _ in range(_FULL_SYNC_MAX_PAGES):
            resp = client.list_messages(query="in:inbox", page_token=page_token)
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        messages = [self.get_message(mid) for mid in ids]
        cursor = client.get_profile().get("historyId", "")
        return SyncResult(messages, cursor=str(cursor), full_sync=True)

    def _incremental_sync(self, client: GmailClient, cursor: str) -> SyncResult:
        added_ids: list[str] = []
        latest_history = cursor
        page_token: str | None = None
        while True:
            resp = client.list_history(cursor, page_token=page_token)
            latest_history = resp.get("historyId", latest_history)
            for record in resp.get("history", []):
                for item in record.get("messagesAdded", []):
                    added_ids.append(item["message"]["id"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        # De-dupe while preserving order.
        seen: set[str] = set()
        unique_ids = [i for i in added_ids if not (i in seen or seen.add(i))]
        messages = [self.get_message(mid) for mid in unique_ids]
        return SyncResult(messages, cursor=str(latest_history))

    # --- sending ---
    def create_draft(self, message: OutgoingMessage) -> str:
        resp = self._require_client().create_draft(
            _build_raw(message), thread_id=message.thread_id
        )
        return resp["id"]

    def send(self, message: OutgoingMessage) -> str:
        resp = self._require_client().send(
            _build_raw(message), thread_id=message.thread_id
        )
        return resp["id"]

    def send_draft(self, draft_id: str) -> str:
        return self._require_client().send_draft(draft_id)["id"]
