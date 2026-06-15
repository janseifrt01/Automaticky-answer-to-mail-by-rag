"""Tests for the web UI routes (Epic 6).

HTMX isn't executed (no browser), so we assert the rendered HTML/fragments and
the persisted state via repos. KB ingest uses the offline FakeProvider.
"""

from __future__ import annotations

import pytest
from app.db.repositories import emails as emails_repo
from app.db.repositories import replies as replies_repo
from app.db.repositories import settings as settings_repo
from app.deps import get_embedder, get_mail

from tests.conftest import FakeMailProvider, FakeProvider


@pytest.fixture
def web_client(client):
    client.app.dependency_overrides[get_embedder] = lambda: FakeProvider()
    yield client
    client.app.dependency_overrides.clear()


def _seed_drafted(conn):
    eid = emails_repo.upsert_email(
        conn, message_id="m1", sender="alice@acme.com",
        subject="Pricing question", body_text="How much?",
    )
    emails_repo.update_status(conn, eid, "drafted")
    replies_repo.create_reply(
        conn, email_id=eid, reply_text="Our plan is $9/mo.",
        sources_used=[{"chunk_id": 1, "source_name": "faq", "score": 0.9}],
        confidence=0.88,
    )
    return eid


# --- pages -------------------------------------------------------------------

def test_dashboard_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "RAG Mail Auto-Reply" in resp.text
    assert "No emails yet" in resp.text


def test_knowledge_page(client):
    resp = client.get("/knowledge")
    assert resp.status_code == 200
    assert "Knowledge Base" in resp.text


def test_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Reply behavior" in resp.text
    assert "Pilot" in resp.text
    assert "Reply model provider" in resp.text


# --- dashboard queue + actions ----------------------------------------------

def test_queue_shows_drafted_email(client):
    _seed_drafted(client.app.state.db)
    resp = client.get("/emails")
    assert "alice@acme.com" in resp.text
    assert "Our plan is $9/mo." in resp.text
    assert "faq" in resp.text  # cited source


def test_edit_reply_persists(client):
    eid = _seed_drafted(client.app.state.db)
    resp = client.post(f"/emails/{eid}/reply", data={"reply_text": "Edited reply."})
    assert resp.status_code == 200
    assert "Edited reply." in resp.text
    reply = replies_repo.get_latest_for_email(client.app.state.db, eid)
    assert reply["reply_text"] == "Edited reply."


def test_approve_sends_via_mail_provider(client):
    eid = _seed_drafted(client.app.state.db)
    fake = FakeMailProvider([])
    client.app.dependency_overrides[get_mail] = lambda: fake
    try:
        resp = client.post(f"/emails/{eid}/approve")
    finally:
        client.app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "sent ✓" in resp.text
    assert len(fake.sent) == 1
    assert emails_repo.get_email(client.app.state.db, eid)["status"] == "sent"


def test_approve_when_not_connected_shows_error(client):
    eid = _seed_drafted(client.app.state.db)
    client.app.dependency_overrides[get_mail] = lambda: FakeMailProvider(
        [], connected=False
    )
    try:
        resp = client.post(f"/emails/{eid}/approve")
    finally:
        client.app.dependency_overrides.clear()
    assert "Gmail not connected" in resp.text
    # Still drafted — nothing sent.
    assert emails_repo.get_email(client.app.state.db, eid)["status"] == "drafted"


def test_discard(client):
    eid = _seed_drafted(client.app.state.db)
    client.post(f"/emails/{eid}/discard")
    assert emails_repo.get_email(client.app.state.db, eid)["status"] == "discarded"


def test_requeue_resets_error(client):
    conn = client.app.state.db
    eid = emails_repo.upsert_email(conn, message_id="e1", subject="x")
    emails_repo.update_status(conn, eid, "error")
    client.post(f"/emails/{eid}/requeue")
    assert emails_repo.get_email(conn, eid)["status"] == "pending"


# --- knowledge base ----------------------------------------------------------

def test_kb_paste_and_delete(web_client):
    resp = web_client.post("/knowledge/paste", data={"label": "faq", "text": "hello"})
    assert resp.status_code == 200
    assert "faq" in resp.text
    # Listed on the page.
    assert "faq" in web_client.get("/knowledge").text
    # Delete returns the (now empty) sources fragment.
    resp = web_client.post("/knowledge/faq/delete")
    assert "Deleted faq" in resp.text


def test_kb_upload_unsupported(web_client):
    resp = web_client.post(
        "/knowledge/upload",
        files={"file": ("image.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 200  # fragment with an inline error
    assert "Unsupported file type" in resp.text


# --- settings ----------------------------------------------------------------

def test_settings_save(client):
    resp = client.post(
        "/settings",
        data={
            "reply_mode": "auto",
            "confidence_threshold": "0.6",
            "auto_send_keywords": "invoice, order",
            "llm_provider": "anthropic",
            "embedding_provider": "github_models",
            "generation_model": "claude-haiku-4-5",
        },
    )
    assert resp.status_code == 200
    assert "Saved." in resp.text
    row = settings_repo.get_settings_row(client.app.state.db)
    assert row["reply_mode"] == "auto"
    assert row["confidence_threshold"] == 0.6
    assert row["auto_send_rules"] == {"keywords": ["invoice", "order"]}
    assert row["llm_provider"] == "anthropic"
    assert row["embedding_provider"] == "github_models"
    assert row["generation_model"] == "claude-haiku-4-5"


# --- sync action -------------------------------------------------------------

def test_action_sync_returns_status_bar(client):
    resp = client.post("/actions/sync")
    assert resp.status_code == 200
    assert "Sync now" in resp.text  # status bar fragment
