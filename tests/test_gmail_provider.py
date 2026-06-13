"""Tests for GmailProvider mapping + sync logic (Tasks 2.4, 2.5, 2.6)."""

from __future__ import annotations

import base64

import pytest
from app.mail.gmail.provider import (
    GmailProvider,
    _build_raw,
    gmail_message_to_domain,
)
from app.mail.models import OutgoingMessage
from googleapiclient.errors import HttpError


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _sample_message(msg_id: str = "msg1") -> dict:
    return {
        "id": msg_id,
        "threadId": "t1",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "To", "value": "me@example.com, bob@example.com"},
                {"name": "Subject", "value": "Hello"},
                {"name": "Message-ID", "value": "<abc@mail>"},
                {"name": "List-Id", "value": "<list.example.com>"},
                {"name": "X-Ignored", "value": "drop me"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Hi there")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>Hi</p>")}},
            ],
        },
    }


def test_mapping_to_domain():
    msg = gmail_message_to_domain(_sample_message())
    assert msg.provider_message_id == "msg1"
    assert msg.thread_id == "t1"
    assert msg.sender == "alice@example.com"
    assert msg.recipients == ["me@example.com", "bob@example.com"]
    assert msg.subject == "Hello"
    assert msg.rfc_message_id == "<abc@mail>"
    assert msg.body_text == "Hi there"  # text/plain preferred over html
    assert msg.headers["list-id"] == "<list.example.com>"
    assert "x-ignored" not in msg.headers  # only kept headers surfaced
    assert msg.received_at.startswith("2023-")  # internalDate -> ISO


def test_mapping_falls_back_to_stripped_html():
    payload = {
        "id": "m",
        "threadId": "t",
        "payload": {
            "mimeType": "text/html",
            "headers": [{"name": "Subject", "value": "S"}],
            "body": {"data": _b64("<p>Hello <b>world</b></p>")},
        },
    }
    msg = gmail_message_to_domain(payload)
    assert msg.body_text == "Hello world"


def test_build_raw_sets_threading_headers():
    out = OutgoingMessage(
        to="bob@x.com",
        subject="Re: Hi",
        body_text="reply body",
        thread_id="t1",
        in_reply_to="<abc@mail>",
        references=["<root@mail>"],
    )
    decoded = base64.urlsafe_b64decode(_build_raw(out)).decode()
    assert "In-Reply-To: <abc@mail>" in decoded
    # References should include prior refs + the in-reply-to id.
    assert "References: <root@mail> <abc@mail>" in decoded
    assert "reply body" in decoded


class FakeGmailClient:
    """Hand-rolled Gmail client for provider tests."""

    def __init__(self, *, history=None, history_error=False):
        self._history = history or {}
        self._history_error = history_error
        self.profile = {"emailAddress": "me@example.com", "historyId": "200"}

    def get_message(self, message_id, fmt="full"):
        return _sample_message(message_id)

    def get_thread(self, thread_id, fmt="full"):
        return {"messages": [_sample_message("a"), _sample_message("b")]}

    def list_messages(self, query=None, page_token=None):
        return {"messages": [{"id": "m1"}]}

    def list_history(self, start_history_id, page_token=None):
        if self._history_error:
            raise HttpError(resp=_FakeResp(404), content=b"expired")
        return self._history

    def get_profile(self):
        return self.profile


class _FakeResp:
    def __init__(self, status):
        self.status = status
        self.reason = "err"


def test_get_thread_returns_all_messages():
    provider = GmailProvider(FakeGmailClient())
    msgs = provider.get_thread("t1")
    assert [m.provider_message_id for m in msgs] == ["a", "b"]


def test_incremental_sync_returns_added_messages():
    history = {
        "historyId": "150",
        "history": [{"messagesAdded": [{"message": {"id": "m9"}}]}],
    }
    provider = GmailProvider(FakeGmailClient(history=history))
    result = provider.fetch_new("100")
    assert [m.provider_message_id for m in result.messages] == ["m9"]
    assert result.cursor == "150"
    assert result.full_sync is False


def test_full_sync_when_cursor_is_none():
    provider = GmailProvider(FakeGmailClient())
    result = provider.fetch_new(None)
    assert [m.provider_message_id for m in result.messages] == ["m1"]
    assert result.cursor == "200"  # from profile historyId
    assert result.full_sync is True


def test_expired_cursor_falls_back_to_full_sync():
    provider = GmailProvider(FakeGmailClient(history_error=True))
    result = provider.fetch_new("stale")
    assert result.full_sync is True
    assert [m.provider_message_id for m in result.messages] == ["m1"]


def test_not_connected_provider_raises_on_use():
    provider = GmailProvider(client=None)
    assert provider.is_connected() is False
    with pytest.raises(RuntimeError):
        provider.get_message("x")
