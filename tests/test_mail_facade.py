"""Tests for the MailProvider facade contract (Task 2.0)."""

from __future__ import annotations

from app.mail.base import MailProvider


def test_fake_provider_satisfies_interface(fake_mail_provider):
    assert isinstance(fake_mail_provider, MailProvider)
    assert fake_mail_provider.is_connected() is True
    assert fake_mail_provider.account_email() == "me@example.com"


def test_send_and_draft_record(fake_mail_provider):
    from app.mail.models import OutgoingMessage

    msg = OutgoingMessage(to="x@y.com", subject="Re: Hi", body_text="hello")
    sent_id = fake_mail_provider.send(msg)
    draft_id = fake_mail_provider.create_draft(msg)
    assert sent_id == "sent-1"
    assert draft_id == "draft-1"
    assert fake_mail_provider.sent == [msg]
    assert fake_mail_provider.drafts == [msg]
