"""Gmail OAuth2: build the consent URL, exchange the code, refresh, disconnect.

Credentials are persisted encrypted (via :class:`TokenCipher` + the credentials
repo) as the JSON produced by ``Credentials.to_json()``. Network calls
(token exchange/refresh) are isolated in small functions so they can be mocked
in tests.
"""

from __future__ import annotations

import json
import sqlite3

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import Settings
from app.db.repositories import credentials as cred_repo
from app.db.repositories import settings as settings_repo
from app.mail.crypto import TokenCipher

PROVIDER = "gmail"


def _client_config(settings: Settings) -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_flow(settings: Settings, state: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(settings),
        scopes=settings.gmail_scopes,
        state=state,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def authorization_url(settings: Settings) -> tuple[str, str]:
    """Return ``(url, state)`` to redirect the user to Google's consent screen."""
    flow = build_flow(settings)
    return flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )


def _store_credentials(
    conn: sqlite3.Connection,
    cipher: TokenCipher,
    creds: Credentials,
    account: str | None,
) -> None:
    secret_enc = cipher.encrypt(creds.to_json())
    cred_repo.save(conn, PROVIDER, account, secret_enc)


def exchange_code(
    conn: sqlite3.Connection,
    settings: Settings,
    cipher: TokenCipher,
    code: str,
    state: str | None = None,
) -> Credentials:
    """Exchange an authorization ``code`` for credentials and store them."""
    flow = build_flow(settings, state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    _store_credentials(conn, cipher, creds, account=None)
    settings_repo.update_settings(conn, gmail_connected=True)
    return creds


def load_credentials(
    conn: sqlite3.Connection,
    settings: Settings,
    cipher: TokenCipher,
) -> Credentials | None:
    """Load stored credentials, refreshing (and re-saving) if expired."""
    secret_enc = cred_repo.load(conn, PROVIDER)
    if secret_enc is None:
        return None
    info = json.loads(cipher.decrypt(secret_enc))
    creds = Credentials.from_authorized_user_info(info, scopes=settings.gmail_scopes)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        account = cred_repo.get_account(conn, PROVIDER)
        _store_credentials(conn, cipher, creds, account=account)
    return creds


def set_account_email(conn: sqlite3.Connection, email: str) -> None:
    """Record the connected account's email in credentials + settings."""
    with conn:
        conn.execute(
            "UPDATE credentials SET account = ? WHERE provider = ?",
            (email, PROVIDER),
        )
    settings_repo.update_settings(conn, gmail_email=email)


def disconnect(conn: sqlite3.Connection) -> None:
    """Remove stored credentials and mark the mailbox disconnected."""
    cred_repo.delete(conn, PROVIDER)
    settings_repo.update_settings(conn, gmail_connected=False, gmail_email=None)
