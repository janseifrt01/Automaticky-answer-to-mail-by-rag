"""Tests for the mail provider factory (Task 2.7)."""

from __future__ import annotations

import pytest
from app.config import Settings
from app.mail.base import MailProvider
from app.mail.factory import get_mail_provider
from cryptography.fernet import Fernet


def _settings(**kw) -> Settings:
    base = dict(
        _env_file=None,
        openai_api_key="x",
        token_encryption_key=Fernet.generate_key().decode(),
    )
    base.update(kw)
    return Settings(**base)


def test_unknown_provider_raises(tmp_db):
    with pytest.raises(ValueError):
        get_mail_provider(tmp_db, _settings(mail_provider="outlook"))


def test_gmail_not_connected_when_no_credentials(tmp_db):
    provider = get_mail_provider(tmp_db, _settings(mail_provider="gmail"))
    assert isinstance(provider, MailProvider)
    assert provider.is_connected() is False
