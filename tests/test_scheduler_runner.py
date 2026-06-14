"""Async tests for the processing cycle (Tasks 5.2, 5.3, 5.6)."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.db.connection import connect
from app.db.repositories import emails as emails_repo
from app.db.repositories import replies as replies_repo
from app.db.schema import bootstrap
from app.rag.retrieval import RetrievedChunk
from app.scheduler import runner

from tests.conftest import FakeMailProvider, FakeProvider

CONFIDENT = RetrievedChunk(
    chunk_id=1, source_name="faq", text="Answer.", score=0.95, distance=0.1
)


class StubLLM(FakeProvider):
    """Content-aware LLM: triage vs generation by system prompt; can raise."""

    def __init__(self, *, triage="answerable", boom_marker=None):
        super().__init__()
        self.triage = triage
        self.boom_marker = boom_marker

    def generate(self, system, user, *, json_schema=None):
        if self.boom_marker and self.boom_marker in user:
            raise RuntimeError("boom")
        if "triage" in system.lower():
            return f'{{"category": "{self.triage}", "reason": "stub"}}'
        return '{"reply": "stub reply", "confidence": 0.9, "should_send": false}'


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, openai_api_key="x", **kw)


def _make_db(tmp_path, emails) -> str:
    db_path = str(tmp_path / "cycle.db")
    conn = connect(db_path)
    bootstrap(conn)
    for e in emails:
        emails_repo.upsert_email(conn, **e)
    conn.close()
    return db_path


def _email(mid, **kw):
    return {"message_id": mid, "sender": "a@x.com", "subject": "Q",
            "body_text": kw.get("body", "When open?"), "thread_id": "t1", **{
                k: v for k, v in kw.items() if k in ("headers",)}}


async def _run(db_path, mail, llm, settings):
    return await runner.run_cycle(
        db_path=db_path,
        mail_provider=mail,
        llm_provider=llm,
        settings=settings,
        lock=asyncio.Lock(),
    )


async def test_processes_pending_into_drafts(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rag.pipeline.retrieve", lambda *a, **k: [CONFIDENT])
    db = _make_db(tmp_path, [_email("m1"), _email("m2"), _email("m3")])
    summary = await _run(db, FakeMailProvider([]), StubLLM(), _settings())
    assert summary["drafted"] == 3
    conn = connect(db)
    assert replies_repo.get_latest_for_email(conn, 1)["reply_text"] == "stub reply"
    assert emails_repo.get_email(conn, 1)["status"] == "drafted"
    conn.close()


async def test_guard_skips_bulk_without_llm(tmp_path):
    db = _make_db(tmp_path, [_email("m1", headers={"list-id": "<l.example>"})])
    summary = await _run(db, FakeMailProvider([]), StubLLM(), _settings())
    assert summary["skipped"] == 1
    assert summary["drafted"] == 0


async def test_low_confidence_routes_to_human(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rag.pipeline.retrieve", lambda *a, **k: [])
    db = _make_db(tmp_path, [_email("m1")])
    summary = await _run(db, FakeMailProvider([]), StubLLM(), _settings())
    assert summary["needs_human"] == 1


async def test_error_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rag.pipeline.retrieve", lambda *a, **k: [CONFIDENT])
    db = _make_db(tmp_path, [_email("ok"), _email("bad", body="please boom now")])
    summary = await _run(
        db, FakeMailProvider([]), StubLLM(boom_marker="boom"), _settings()
    )
    assert summary["drafted"] == 1
    assert summary["errors"] == 1
    conn = connect(db)
    statuses = {e["message_id"]: e["status"] for e in emails_repo.list_emails(conn)}
    assert statuses["bad"] == "error"
    conn.close()


async def test_concurrency_processes_all(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rag.pipeline.retrieve", lambda *a, **k: [CONFIDENT])
    db = _make_db(tmp_path, [_email(f"m{i}") for i in range(6)])
    settings = _settings(max_concurrency=4)
    summary = await _run(db, FakeMailProvider([]), StubLLM(), settings)
    assert summary["drafted"] == 6


async def test_single_flight_skips_overlapping_run(tmp_path):
    db = _make_db(tmp_path, [_email("m1")])
    lock = asyncio.Lock()
    await lock.acquire()
    try:
        out = await runner.run_cycle(
            db_path=db,
            mail_provider=FakeMailProvider([]),
            llm_provider=StubLLM(),
            settings=_settings(),
            lock=lock,
        )
        assert out["status"] == "skipped"
    finally:
        lock.release()


async def test_sync_brings_in_new_mail(tmp_path, monkeypatch):
    from tests.conftest import make_email

    monkeypatch.setattr("app.rag.pipeline.retrieve", lambda *a, **k: [CONFIDENT])
    db = _make_db(tmp_path, [])
    mail = FakeMailProvider([make_email("inbox1", sender="c@x.com")])
    summary = await _run(db, mail, StubLLM(), _settings())
    assert summary["synced"] == 1
    assert summary["drafted"] == 1
