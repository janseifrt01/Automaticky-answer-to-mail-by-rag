"""Tests for Gmail OAuth2 token storage + refresh (Task 2.2).

Google network objects are mocked; no real OAuth happens.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.db.repositories import credentials as cred_repo
from app.db.repositories import settings as settings_repo
from app.mail.crypto import TokenCipher
from app.mail.gmail import auth
from cryptography.fernet import Fernet


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="x",
        token_encryption_key=Fernet.generate_key().decode(),
    )


class _FakeCreds:
    def __init__(self, json_str: str):
        self.valid = True
        self.refresh_token = "r"
        self._json = json_str

    def to_json(self) -> str:
        return self._json


class _FakeFlow:
    def __init__(self):
        self.credentials = _FakeCreds('{"token": "abc", "refresh_token": "r"}')

    def fetch_token(self, code=None):
        self.code = code


def test_exchange_code_stores_encrypted_and_marks_connected(
    tmp_db, settings, monkeypatch
):
    monkeypatch.setattr(auth, "build_flow", lambda s, state=None: _FakeFlow())
    cipher = TokenCipher(settings.token_encryption_key)

    auth.exchange_code(tmp_db, settings, cipher, code="the-code")

    stored = cred_repo.load(tmp_db, "gmail")
    assert stored is not None
    assert cipher.decrypt(stored) == '{"token": "abc", "refresh_token": "r"}'
    assert settings_repo.get_settings_row(tmp_db)["gmail_connected"] is True


def test_load_credentials_refreshes_when_expired(tmp_db, settings, monkeypatch):
    cipher = TokenCipher(settings.token_encryption_key)
    cred_repo.save(tmp_db, "gmail", "me@x.com", cipher.encrypt('{"token": "old"}'))

    class _Refreshable:
        def __init__(self):
            self.valid = False
            self.refresh_token = "r"

        def refresh(self, request):
            self.valid = True

        def to_json(self):
            return '{"token": "new"}'

    monkeypatch.setattr(
        auth.Credentials,
        "from_authorized_user_info",
        lambda info, scopes=None: _Refreshable(),
    )

    creds = auth.load_credentials(tmp_db, settings, cipher)
    assert creds.valid is True
    # Refreshed token was re-encrypted and stored; account preserved.
    assert cipher.decrypt(cred_repo.load(tmp_db, "gmail")) == '{"token": "new"}'
    assert cred_repo.get_account(tmp_db, "gmail") == "me@x.com"


def test_load_credentials_none_when_absent(tmp_db, settings):
    cipher = TokenCipher(settings.token_encryption_key)
    assert auth.load_credentials(tmp_db, settings, cipher) is None


def test_disconnect_clears_state(tmp_db, settings):
    cipher = TokenCipher(settings.token_encryption_key)
    cred_repo.save(tmp_db, "gmail", "me@x.com", cipher.encrypt("{}"))
    settings_repo.update_settings(tmp_db, gmail_connected=True, gmail_email="me@x.com")

    auth.disconnect(tmp_db)

    assert cred_repo.load(tmp_db, "gmail") is None
    row = settings_repo.get_settings_row(tmp_db)
    assert row["gmail_connected"] is False
    assert row["gmail_email"] is None
