"""Tests for credential encryption (Task 2.1)."""

from __future__ import annotations

import pytest
from app.mail.crypto import TokenCipher
from cryptography.fernet import Fernet


def test_round_trip():
    cipher = TokenCipher(Fernet.generate_key())
    token = cipher.encrypt('{"token": "secret"}')
    assert token != b'{"token": "secret"}'  # ciphertext differs from plaintext
    assert cipher.decrypt(token) == '{"token": "secret"}'


def test_empty_key_raises():
    with pytest.raises(ValueError):
        TokenCipher("")
