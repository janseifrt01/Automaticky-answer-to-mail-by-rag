"""End-to-end pipeline branch tests (Task 4.6)."""

from __future__ import annotations

import pytest
from app.config import Settings
from app.db.repositories import emails as emails_repo
from app.db.repositories import replies as replies_repo
from app.rag import pipeline
from app.rag.retrieval import RetrievedChunk

from tests.conftest import ScriptedProvider

TRIAGE_ANSWERABLE = '{"category": "answerable", "reason": "question"}'
TRIAGE_NO_REPLY = '{"category": "no_reply", "reason": "newsletter"}'
TRIAGE_NEEDS_HUMAN = '{"category": "needs_human", "reason": "complaint"}'
GEN_OK = '{"reply": "We open at 9am.", "confidence": 0.9, "should_send": true}'


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="x")


def _make_email(conn, *, headers=None, sender="a@x.com"):
    eid = emails_repo.upsert_email(
        conn,
        message_id="m1",
        sender=sender,
        subject="Hours",
        body_text="When do you open?",
        headers=headers,
    )
    return emails_repo.get_email(conn, eid)


def _patch_retrieve(monkeypatch, chunks):
    monkeypatch.setattr(pipeline, "retrieve", lambda *a, **k: chunks)


def _run(tmp_db, vector_store, provider, email, settings):
    return pipeline.process_email(
        tmp_db, vector_store, provider, email, settings=settings
    )


def test_guard_skips_without_llm(tmp_db, vector_store, settings):
    email = _make_email(tmp_db, headers={"list-id": "<l.example.com>"})
    provider = ScriptedProvider([])  # must not be called
    out = _run(tmp_db, vector_store, provider, email, settings)
    assert out["status"] == pipeline.STATUS_SKIPPED
    assert provider.calls == []
    assert emails_repo.get_email(tmp_db, email["id"])["status"] == "skipped"


def test_triage_no_reply_skips(tmp_db, vector_store, settings):
    email = _make_email(tmp_db)
    provider = ScriptedProvider([TRIAGE_NO_REPLY])
    out = _run(tmp_db, vector_store, provider, email, settings)
    assert out["status"] == pipeline.STATUS_SKIPPED
    assert out["category"] == "no_reply"


def test_triage_needs_human(tmp_db, vector_store, settings):
    email = _make_email(tmp_db)
    provider = ScriptedProvider([TRIAGE_NEEDS_HUMAN])
    out = _run(tmp_db, vector_store, provider, email, settings)
    assert out["status"] == pipeline.STATUS_NEEDS_HUMAN


def test_low_confidence_routes_to_human(tmp_db, vector_store, settings, monkeypatch):
    email = _make_email(tmp_db)
    _patch_retrieve(monkeypatch, [])  # empty KB → no confident answer
    provider = ScriptedProvider([TRIAGE_ANSWERABLE])
    out = _run(tmp_db, vector_store, provider, email, settings)
    assert out["status"] == pipeline.STATUS_NEEDS_HUMAN
    assert replies_repo.get_latest_for_email(tmp_db, email["id"]) is None


def test_answerable_and_confident_drafts_reply(
    tmp_db, vector_store, settings, monkeypatch
):
    email = _make_email(tmp_db)
    chunk = RetrievedChunk(
        chunk_id=1, source_name="faq", text="We open at 9am.", score=0.9, distance=0.2
    )
    _patch_retrieve(monkeypatch, [chunk])
    provider = ScriptedProvider([TRIAGE_ANSWERABLE, GEN_OK])
    out = _run(tmp_db, vector_store, provider, email, settings)

    assert out["status"] == pipeline.STATUS_DRAFTED
    assert out["reply_id"] is not None
    reply = replies_repo.get_latest_for_email(tmp_db, email["id"])
    assert reply["reply_text"] == "We open at 9am."
    assert reply["confidence"] == 0.9
    assert reply["sources_used"] == [
        {"chunk_id": 1, "source_name": "faq", "score": 0.9}
    ]
    assert emails_repo.get_email(tmp_db, email["id"])["status"] == "drafted"
