"""Mail provider selection. Gmail is the only v1 implementation."""

from __future__ import annotations

import sqlite3

from app.config import Settings, get_settings
from app.db.repositories import credentials as cred_repo
from app.mail.base import MailProvider
from app.mail.crypto import TokenCipher


def build_gmail_client(conn: sqlite3.Connection, settings: Settings):
    """Build a connected ``GmailClient``, or ``None`` if no stored credentials.

    Lazily imports the Google client so it isn't pulled in unless mail is used.
    """
    from app.mail.gmail import auth
    from app.mail.gmail.client import GmailClient

    cipher = TokenCipher(settings.token_encryption_key)
    creds = auth.load_credentials(conn, settings, cipher)
    if creds is None:
        return None

    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return GmailClient(service)


def _build_gmail(conn: sqlite3.Connection, settings: Settings) -> MailProvider:
    from app.mail.gmail import auth
    from app.mail.gmail.provider import GmailProvider

    client = build_gmail_client(conn, settings)
    if client is None:
        # Not connected: a provider whose is_connected() is False.
        return GmailProvider(client=None, account_email=None)
    account = cred_repo.get_account(conn, auth.PROVIDER)
    return GmailProvider(client, account_email=account)


def get_mail_provider(
    conn: sqlite3.Connection, settings: Settings | None = None
) -> MailProvider:
    """Build the configured mail provider, bound to ``conn``."""
    settings = settings or get_settings()
    if settings.mail_provider == "gmail":
        return _build_gmail(conn, settings)
    raise ValueError(f"Unknown mail provider: {settings.mail_provider!r}")
