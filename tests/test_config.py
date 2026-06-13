"""Tests for the settings layer (Task 0.2)."""

from __future__ import annotations

import pytest
from app.config import ReplyMode, Settings
from pydantic import ValidationError


def test_defaults_with_required_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.openai_api_key == "sk-test"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.generation_model == "gpt-4o-mini"
    assert settings.confidence_threshold == 0.75
    assert settings.reply_mode is ReplyMode.PILOT
    assert settings.sync_interval_min == 5


def test_overrides_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.5")
    monkeypatch.setenv("REPLY_MODE", "auto")
    settings = Settings(_env_file=None)
    assert settings.confidence_threshold == 0.5
    assert settings.reply_mode is ReplyMode.AUTO


def test_missing_required_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
