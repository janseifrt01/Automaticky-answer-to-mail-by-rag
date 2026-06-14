"""Thin wrapper over the Gmail API resource with retry/backoff.

Wraps a built ``googleapiclient`` ``service`` so the :class:`GmailProvider`
deals in simple method calls. Transient errors (HTTP 429/5xx) are retried with
capped exponential backoff; other errors propagate.
"""

from __future__ import annotations

import time
from typing import Any

from googleapiclient.errors import HttpError

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 4


def _execute(request: Any, *, _sleep=time.sleep) -> dict:
    """Execute a Gmail API request, retrying transient failures."""
    delay = 1.0
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return request.execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if int(status or 0) in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                _sleep(delay)
                delay *= 2
                continue
            raise


class GmailClient:
    """Wraps the Gmail ``users()`` resource for the connected mailbox."""

    def __init__(self, service: Any, user_id: str = "me") -> None:
        self._svc = service
        self._user = user_id

    def get_profile(self) -> dict:
        return _execute(self._svc.users().getProfile(userId=self._user))

    def get_message(self, message_id: str, fmt: str = "full") -> dict:
        return _execute(
            self._svc.users().messages().get(
                userId=self._user, id=message_id, format=fmt
            )
        )

    def get_thread(self, thread_id: str, fmt: str = "full") -> dict:
        return _execute(
            self._svc.users().threads().get(
                userId=self._user, id=thread_id, format=fmt
            )
        )

    def list_messages(
        self, query: str | None = None, page_token: str | None = None
    ) -> dict:
        return _execute(
            self._svc.users().messages().list(
                userId=self._user, q=query, pageToken=page_token
            )
        )

    def list_history(
        self, start_history_id: str, page_token: str | None = None
    ) -> dict:
        return _execute(
            self._svc.users().history().list(
                userId=self._user,
                startHistoryId=start_history_id,
                pageToken=page_token,
                historyTypes=["messageAdded"],
            )
        )

    def create_draft(self, raw: str, thread_id: str | None = None) -> dict:
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        return _execute(
            self._svc.users().drafts().create(
                userId=self._user, body={"message": message}
            )
        )

    def send(self, raw: str, thread_id: str | None = None) -> dict:
        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        return _execute(
            self._svc.users().messages().send(userId=self._user, body=body)
        )

    def send_draft(self, draft_id: str) -> dict:
        return _execute(
            self._svc.users().drafts().send(
                userId=self._user, body={"id": draft_id}
            )
        )

    def delete_draft(self, draft_id: str) -> None:
        _execute(self._svc.users().drafts().delete(userId=self._user, id=draft_id))
