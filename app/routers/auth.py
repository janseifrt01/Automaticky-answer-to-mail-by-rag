"""Gmail OAuth2 connect / callback / disconnect routes.

Minimal flow wiring; the Settings UI (Epic 6) links to these. State is held on
``app.state`` for CSRF protection in this single-user local app.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.db.repositories import credentials as cred_repo
from app.mail.crypto import TokenCipher
from app.mail.factory import build_gmail_client
from app.mail.gmail import auth

router = APIRouter(prefix="/auth/gmail", tags=["auth"])


@router.get("/connect")
def connect(request: Request) -> RedirectResponse:
    settings = get_settings()
    url, state = auth.authorization_url(settings)
    request.app.state.oauth_state = state
    return RedirectResponse(url)


@router.get("/callback")
def callback(request: Request, code: str, state: str | None = None):
    settings = get_settings()
    expected = getattr(request.app.state, "oauth_state", None)
    if expected is not None and state != expected:
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    conn = request.app.state.db
    cipher = TokenCipher(settings.token_encryption_key)
    auth.exchange_code(conn, settings, cipher, code=code, state=state)

    # Record the connected account's email (live profile lookup).
    client = build_gmail_client(conn, settings)
    if client is not None:
        email = client.get_profile().get("emailAddress")
        if email:
            auth.set_account_email(conn, email)

    return {"status": "connected", "account": cred_repo.get_account(conn, "gmail")}


@router.post("/disconnect")
def disconnect(request: Request) -> dict[str, str]:
    auth.disconnect(request.app.state.db)
    return {"status": "disconnected"}
