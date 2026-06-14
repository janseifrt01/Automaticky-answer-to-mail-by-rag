"""Tests for the send service (Tasks 7.0, 7.1, 7.2)."""

from __future__ import annotations

from app.db.repositories import emails as emails_repo
from app.db.repositories import replies as replies_repo
from app.mail import sender

from tests.conftest import FakeMailProvider


def _email_and_reply(conn, **email_kw):
    eid = emails_repo.upsert_email(
        conn,
        message_id="m1",
        sender="Alice <alice@acme.com>",
        subject="Pricing",
        body_text="How much?",
        thread_id="t1",
        headers={"message-id": "<orig@acme.com>", "references": "<root@acme.com>"},
        **email_kw,
    )
    emails_repo.update_status(conn, eid, "drafted")
    rid = replies_repo.create_reply(
        conn, email_id=eid, reply_text="It's $9/mo.", confidence=0.9, should_send=True
    )
    return emails_repo.get_email(conn, eid), replies_repo.get_reply(conn, rid)


def test_build_outgoing_threading():
    email = {
        "sender": "Alice <alice@acme.com>",
        "subject": "Pricing",
        "thread_id": "t1",
        "headers": {"message-id": "<orig@acme.com>", "references": "<root@acme.com>"},
    }
    out = sender.build_outgoing(email, {"reply_text": "hello"})
    assert out.to == "alice@acme.com"
    assert out.subject == "Re: Pricing"
    assert out.thread_id == "t1"
    assert out.in_reply_to == "<orig@acme.com>"
    assert out.references == ["<root@acme.com>"]


def test_build_outgoing_no_double_re_prefix():
    out = sender.build_outgoing(
        {"sender": "a@x.com", "subject": "Re: Hi", "headers": {}}, {"reply_text": "x"}
    )
    assert out.subject == "Re: Hi"


def test_send_reply_marks_sent_and_deletes_draft(tmp_db):
    email, reply = _email_and_reply(tmp_db)
    replies_repo.update_reply(tmp_db, reply["id"], gmail_draft_id="draft-1")
    reply = replies_repo.get_reply(tmp_db, reply["id"])
    provider = FakeMailProvider([])

    sender.send_reply(tmp_db, provider, email, reply)

    assert len(provider.sent) == 1
    assert provider.deleted_drafts == ["draft-1"]  # stale draft cleaned up
    assert emails_repo.get_email(tmp_db, email["id"])["status"] == "sent"


def test_send_reply_is_idempotent(tmp_db):
    email, reply = _email_and_reply(tmp_db)
    provider = FakeMailProvider([])
    sender.send_reply(tmp_db, provider, email, reply)
    # Reload (now 'sent') and try again → no second send.
    email = emails_repo.get_email(tmp_db, email["id"])
    sender.send_reply(tmp_db, provider, email, reply)
    assert len(provider.sent) == 1


def test_create_gmail_draft_stores_id(tmp_db):
    email, reply = _email_and_reply(tmp_db)
    provider = FakeMailProvider([])
    draft_id = sender.create_gmail_draft(tmp_db, provider, email, reply)
    assert provider.drafts  # a draft was created
    assert replies_repo.get_reply(tmp_db, reply["id"])["gmail_draft_id"] == draft_id


# --- auto-send gate matrix ---------------------------------------------------

BASE_SETTINGS = {
    "reply_mode": "auto",
    "confidence_threshold": 0.75,
    "auto_send_rules": None,
}
ANSWERABLE = {"triage_category": "answerable", "subject": "Q", "body_text": "b"}
GOOD_REPLY = {"should_send": True, "confidence": 0.9}


def test_auto_send_all_gates_pass():
    assert sender.should_auto_send(ANSWERABLE, GOOD_REPLY, BASE_SETTINGS) is True


def test_auto_send_blocked_in_pilot():
    s = {**BASE_SETTINGS, "reply_mode": "pilot"}
    assert sender.should_auto_send(ANSWERABLE, GOOD_REPLY, s) is False


def test_auto_send_blocked_below_threshold():
    reply = {"should_send": True, "confidence": 0.5}
    assert sender.should_auto_send(ANSWERABLE, reply, BASE_SETTINGS) is False


def test_auto_send_blocked_when_model_defers():
    reply = {"should_send": False, "confidence": 0.9}
    assert sender.should_auto_send(ANSWERABLE, reply, BASE_SETTINGS) is False


def test_auto_send_blocked_when_not_answerable():
    email = {**ANSWERABLE, "triage_category": "needs_human"}
    assert sender.should_auto_send(email, GOOD_REPLY, BASE_SETTINGS) is False


def test_auto_send_keyword_rule_must_match():
    s = {**BASE_SETTINGS, "auto_send_rules": {"keywords": ["invoice"]}}
    assert sender.should_auto_send(ANSWERABLE, GOOD_REPLY, s) is False
    match = {
        "triage_category": "answerable",
        "subject": "Invoice question",
        "body_text": "b",
    }
    assert sender.should_auto_send(match, GOOD_REPLY, s) is True
