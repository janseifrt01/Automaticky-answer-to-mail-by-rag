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

    # --- Google OAuth2 / Gmail (populated when Epic 2 lands) ---
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- Storage ---
    db_path: str = "./data/app.db"

    # --- Models (provider-swappable) ---
    embedding_model: str = "text-embedding-3-small"
    generation_model: str = "gpt-4o-mini"

    # --- RAG / behavior ---
    confidence_threshold: float = 0.75
    reply_mode: ReplyMode = ReplyMode.PILOT
    sync_interval_min: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()  # type: ignore[call-arg]  # values come from env/.env
