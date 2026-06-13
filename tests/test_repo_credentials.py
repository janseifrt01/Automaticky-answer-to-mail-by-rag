"""Tests for the credentials repository (Task 2.1)."""

from __future__ import annotations

from app.db.repositories import credentials as cred_repo


def test_save_load_and_account(tmp_db):
    cred_repo.save(tmp_db, "gmail", "me@example.com", b"ciphertext")
    assert cred_repo.load(tmp_db, "gmail") == b"ciphertext"
    assert cred_repo.get_account(tmp_db, "gmail") == "me@example.com"


def test_save_replaces_existing(tmp_db):
    cred_repo.save(tmp_db, "gmail", "a@x.com", b"v1")
    cred_repo.save(tmp_db, "gmail", "a@x.com", b"v2")
    assert cred_repo.load(tmp_db, "gmail") == b"v2"
    (count,) = tmp_db.execute("SELECT COUNT(*) FROM credentials").fetchone()
    assert count == 1


def test_load_missing_returns_none(tmp_db):
    assert cred_repo.load(tmp_db, "gmail") is None
    assert cred_repo.get_account(tmp_db, "gmail") is None


def test_delete(tmp_db):
    cred_repo.save(tmp_db, "gmail", None, b"v1")
    cred_repo.delete(tmp_db, "gmail")
    assert cred_repo.load(tmp_db, "gmail") is None
