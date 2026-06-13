"""Shared test fixtures: temp DB, test client, and an offline fake provider.

Tests run fully offline — no OpenAI/Gmail network calls, no real API key.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from app.db.connection import connect
from app.db.schema import EMBEDDING_DIM, bootstrap
from app.db.vector_store import SqliteVecStore
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_db(tmp_path) -> Iterator[sqlite3.Connection]:
    """A bootstrapped temp-file SQLite DB with sqlite-vec loaded."""
    db_file = tmp_path / "test.db"
    conn = connect(str(db_file))
    bootstrap(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def vector_store(tmp_db) -> SqliteVecStore:
    """A SqliteVecStore bound to the temp DB connection."""
    return SqliteVecStore(tmp_db)


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A TestClient whose app uses a temp DB (via DB_PATH override)."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))

    # Import after env is set so settings pick up the temp DB path.
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


class FakeProvider:
    """Deterministic, offline embedding + generation provider for tests."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic vector seeded by text length; unit-ish values.
        return [[float((len(t) + i) % 7) for i in range(self.dim)] for t in texts]

    def generate(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
    ) -> str:
        return "fake reply"


@pytest.fixture
def fake_provider() -> FakeProvider:
    """An offline provider implementing the embed/generate interface."""
    return FakeProvider()
