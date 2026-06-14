"""Application configuration loaded from environment / .env.

See ``.env.example`` for the documented keys. ``get_settings()`` is the
cached accessor used across the app and as a FastAPI dependency.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ReplyMode(str, Enum):
    """How replies are dispatched."""

    PILOT = "pilot"  # every draft reviewed before sending (default)
    AUTO = "auto"  # auto-send when all guards pass


class Settings(BaseSettings):
    """Typed application settings.

    Required keys fail fast at startup with a clear validation error.
    """

    # --- OpenAI (required) ---
    openai_api_key: str

    # --- Google OAuth2 / Gmail ---
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- Mail integration (Epic 2) ---
    mail_provider: str = "gmail"
    # Fernet key used to encrypt stored OAuth credentials. Required to connect
    # a mailbox; not required just to boot the app. Generate with
    # cryptography.fernet.Fernet.generate_key().
    token_encryption_key: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/gmail/callback"
    # Minimal Gmail scopes: read messages/history + create drafts and send.
    gmail_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ]

    # --- Storage ---
    db_path: str = "./data/app.db"

    # --- Models (provider-swappable) ---
    embedding_model: str = "text-embedding-3-small"
    generation_model: str = "gpt-4o-mini"

    # --- RAG / behavior ---
    confidence_threshold: float = 0.75
    reply_mode: ReplyMode = ReplyMode.PILOT
    sync_interval_min: int = 5
    # Knowledge-base chunking + retrieval
    chunk_size: int = 1000
    chunk_overlap: int = 150
    retrieval_top_k: int = 5
    # Scheduler / async processing
    scheduler_enabled: bool = True
    max_concurrency: int = 4

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
