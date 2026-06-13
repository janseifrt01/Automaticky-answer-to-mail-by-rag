"""Small shared helpers for the data-access layer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (storage format for timestamps)."""
    return datetime.now(UTC).isoformat()


def to_json(value: Any) -> str | None:
    """Serialize a Python value to a JSON string, or ``None`` if value is None."""
    if value is None:
        return None
    return json.dumps(value)


def from_json(value: str | None) -> Any:
    """Parse a JSON string column back to Python, or ``None`` if empty."""
    if value is None or value == "":
        return None
    return json.loads(value)
