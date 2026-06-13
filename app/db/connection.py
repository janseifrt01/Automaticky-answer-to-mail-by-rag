"""SQLite connection helpers with the ``sqlite-vec`` extension loaded.

The whole app (relational data + vectors) lives in a single SQLite file, so
opening a connection also loads ``sqlite-vec`` and applies sensible pragmas.
Access is synchronous, which is fine for a single-user local deployment.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with ``sqlite-vec`` loaded and pragmas set.

    Creates the parent directory if needed. Callers own the connection's
    lifecycle (close it when done).
    """
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Load the sqlite-vec extension, then re-disable extension loading.
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def vec_version(conn: sqlite3.Connection) -> str:
    """Return the loaded ``sqlite-vec`` version (proves the extension loaded)."""
    (version,) = conn.execute("SELECT vec_version();").fetchone()
    return version
