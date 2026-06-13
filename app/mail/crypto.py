"""Symmetric encryption for credentials at rest (Fernet)."""

from __future__ import annotations

from cryptography.fernet import Fernet


class TokenCipher:
    """Encrypts/decrypts secret strings with a Fernet key.

    The key comes from ``Settings.token_encryption_key`` (generate one with
    ``cryptography.fernet.Fernet.generate_key()``). Losing the key makes stored
    credentials unrecoverable — re-authentication is then required.
    """

    def __init__(self, key: str | bytes) -> None:
        if not key:
            raise ValueError(
                "token_encryption_key is not set; cannot encrypt credentials"
            )
        if isinstance(key, str):
            key = key.encode()
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode()
