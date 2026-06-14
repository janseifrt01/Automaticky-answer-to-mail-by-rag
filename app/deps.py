"""Shared FastAPI dependencies.

Provides the per-request DB connection, the embedding/LLM provider, and the
vector store. Tests override ``get_embedder`` to stay offline.
"""

from __future__ import annotations

import sqlite3

from fastapi import Request

from app.config import get_settings
from app.db.vector_store import SqliteVecStore
from app.mail.base import MailProvider
from app.mail.factory import get_mail_provider
from app.providers import get_provider
from app.providers.base import Provider


def get_db(request: Request) -> sqlite3.Connection:
    """The application's SQLite connection (opened at startup)."""
    return request.app.state.db


def get_embedder() -> Provider:
    """The configured embedding/generation provider (OpenAI by default)."""
    return get_provider()


def get_mail(request: Request) -> MailProvider:
    """The configured mail provider bound to the app connection."""
    return get_mail_provider(request.app.state.db, get_settings())


def get_vector_store(request: Request) -> SqliteVecStore:
    """A vector store bound to the app connection."""
    return SqliteVecStore(request.app.state.db)
