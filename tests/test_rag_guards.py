"""Tests for safe-sender / loop guards (Task 4.1)."""

from __future__ import annotations

from app.rag.guards import check_guards
from app.rag.triage import TriageCategory


def _email(sender="alice@example.com", headers=None):
    return {"sender": sender, "headers": headers or {}}


def test_clean_mail_passes():
    assert check_guards(_email()) is None


def test_auto_submitted_blocks():
    r = check_guards(_email(headers={"auto-submitted": "auto-replied"}))
    assert r.category == TriageCategory.NO_REPLY.value


def test_auto_submitted_no_is_allowed():
    assert check_guards(_email(headers={"auto-submitted": "no"})) is None


def test_list_id_blocks():
    r = check_guards(_email(headers={"list-id": "<l.example.com>"}))
    assert r.category == TriageCategory.NO_REPLY.value


def test_bulk_precedence_blocks():
    r = check_guards(_email(headers={"precedence": "bulk"}))
    assert r.category == TriageCategory.NO_REPLY.value


def test_no_reply_sender_blocks():
    r = check_guards(_email(sender="no-reply@service.com"))
    assert r.category == TriageCategory.NO_REPLY.value


def test_own_mail_blocks():
    r = check_guards(
        _email(sender="Me <me@example.com>"), account_email="me@example.com"
    )
    assert r.category == TriageCategory.NO_REPLY.value
