"""Shared test fixtures: temp DB, test client, and an offline fake provider.

Tests run fully offline — no OpenAI/Gmail network calls, no real API key.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from app.db.connection import connect
from app.db.schema import EMBEDDING_DIM, bootstrap
from app.db.vector_store import SqliteVecStore
from app.mail.models import EmailMessage, OutgoingMessage, SyncResult
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_db(tmp_path) -> Iterator[sqlite3.Connection]:
    """A bootstrapped temp-file SQLite DB with sqlite-vec loaded."""
    db_file = tmp_path / "test.db"
    conn = connect(str(db_file))
    bootstrap(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def vector_store(tmp_db) -> SqliteVecStore:
    """A SqliteVecStore bound to the temp DB connection."""
    return SqliteVecStore(tmp_db)


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A TestClient whose app uses a temp DB (via DB_PATH override)."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")  # no background job in tests

    # Import after env is set so settings pick up the temp DB path.
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


class FakeProvider:
    """Deterministic, offline embedding + generation provider for tests."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic vector seeded by text length; unit-ish values.
        return [[float((len(t) + i) % 7) for i in range(self.dim)] for t in texts]

    def generate(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
    ) -> str:
        return "fake reply"


class ScriptedProvider(FakeProvider):
    """Offline provider whose ``generate`` returns queued responses in order.

    Embeddings are inherited (deterministic). Each ``generate`` call pops the
    next scripted response; records calls for assertions.
    """

    def __init__(self, responses: list[str] | None = None, dim: int = EMBEDDING_DIM):
        super().__init__(dim)
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str, *, json_schema: dict | None = None):
        self.calls.append((system, user))
        return self.responses.pop(0) if self.responses else "{}"


@pytest.fixture
def fake_provider() -> FakeProvider:
    """An offline provider implementing the embed/generate interface."""
    return FakeProvider()


class FakeMailProvider:
    """In-memory MailProvider for tests (reusable by later epics).

    ``fetch_new`` returns the configured inbox each call with a cursor derived
    from the message count, so repeated syncs are naturally idempotent.
    """

    def __init__(
        self,
        messages: list[EmailMessage] | None = None,
        *,
        connected: bool = True,
        email: str | None = "me@example.com",
    ) -> None:
        self._messages = messages or []
        self._connected = connected
        self._email = email
        self.sent: list[OutgoingMessage] = []
        self.drafts: list[OutgoingMessage] = []
        self.sent_drafts: list[str] = []
        self.deleted_drafts: list[str] = []

    def is_connected(self) -> bool:
        return self._connected

    def account_email(self) -> str | None:
        return self._email

    def fetch_new(self, cursor: str | None) -> SyncResult:
        return SyncResult(
            list(self._messages),
            cursor=str(len(self._messages)),
            full_sync=cursor is None,
        )

    def get_message(self, message_id: str) -> EmailMessage:
        for m in self._messages:
            if m.provider_message_id == message_id:
                return m
        raise KeyError(message_id)

    def get_thread(self, thread_id: str) -> list[EmailMessage]:
        return [m for m in self._messages if m.thread_id == thread_id]

    def create_draft(self, message: OutgoingMessage) -> str:
        self.drafts.append(message)
        return f"draft-{len(self.drafts)}"

    def send(self, message: OutgoingMessage) -> str:
        self.sent.append(message)
        return f"sent-{len(self.sent)}"

    def send_draft(self, draft_id: str) -> str:
        self.sent_drafts.append(draft_id)
        return f"sent-{draft_id}"

    def delete_draft(self, draft_id: str) -> None:
        self.deleted_drafts.append(draft_id)


def make_email(message_id: str, *, thread_id: str = "t1", **kw) -> EmailMessage:
    """Build an EmailMessage with sensible defaults for tests."""
    return EmailMessage(
        provider_message_id=message_id,
        thread_id=thread_id,
        rfc_message_id=kw.get("rfc_message_id", f"<{message_id}@mail>"),
        sender=kw.get("sender", "alice@example.com"),
        recipients=kw.get("recipients", ["me@example.com"]),
        subject=kw.get("subject", "Subject"),
        body_text=kw.get("body_text", "Body"),
        headers=kw.get("headers", {}),
        received_at=kw.get("received_at", "2026-01-01T00:00:00+00:00"),
    )


@pytest.fixture
def fake_mail_provider() -> FakeMailProvider:
    """A connected in-memory mail provider with two messages."""
    return FakeMailProvider([make_email("m1"), make_email("m2", thread_id="t2")])
