"""Vector storage abstraction (sqlite-vec today, pgvector-ready)."""

from app.db.vector_store.base import VectorStore
from app.db.vector_store.sqlite_vec_store import SqliteVecStore

__all__ = ["VectorStore", "SqliteVecStore"]
