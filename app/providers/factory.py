"""Provider selection. OpenAI is the default; swap here for another provider."""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.base import Provider
from app.providers.openai_provider import build_openai_provider


def build_provider(settings: Settings) -> Provider:
    """Construct the configured provider. Currently OpenAI only."""
    return build_openai_provider(settings)


@lru_cache
def get_provider() -> Provider:
    """Return the cached provider singleton built from app settings."""
    return build_provider(get_settings())
