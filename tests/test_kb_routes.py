"""Tests for the KB management routes (Task 3.4).

The embedding provider is overridden with the offline FakeProvider.
"""

from __future__ import annotations

import pytest
from app.deps import get_embedder

from tests.conftest import FakeProvider


@pytest.fixture
def kb_client(client):
    client.app.dependency_overrides[get_embedder] = lambda: FakeProvider()
    yield client
    client.app.dependency_overrides.clear()


def test_paste_then_list_then_delete(kb_client):
    resp = kb_client.post("/kb/paste", json={"text": "hello world", "label": "faq"})
    assert resp.status_code == 200
    assert resp.json()["chunks"] >= 1

    listed = kb_client.get("/kb").json()["sources"]
    assert any(s["source_name"] == "faq" for s in listed)

    deleted = kb_client.delete("/kb/faq").json()
    assert deleted["deleted"] >= 1
    assert kb_client.get("/kb").json()["sources"] == []


def test_upload_txt_file(kb_client):
    resp = kb_client.post(
        "/kb/upload",
        files={"file": ("doc.txt", b"some knowledge content", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["chunks"] >= 1
    assert resp.json()["source_name"] == "doc.txt"


def test_upload_unsupported_type_returns_415(kb_client):
    resp = kb_client.post(
        "/kb/upload",
        files={"file": ("image.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 415
