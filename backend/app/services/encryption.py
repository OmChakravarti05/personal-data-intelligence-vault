import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12
TAG_SIZE = 16


class DecryptionError(Exception):
    """The data is corrupted, was tampered with, or the key is wrong."""


class FileEncryptor:
    """AES-256-GCM authenticated encryption. Stored format: nonce + ciphertext."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Key must be exactly 32 bytes")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, associated_data: bytes) -> bytes:
        nonce = os.urandom(NONCE_SIZE)
        return nonce + self._aead.encrypt(nonce, plaintext, associated_data)

    def decrypt(self, blob: bytes, associated_data: bytes) -> bytes:
        if len(blob) < NONCE_SIZE + TAG_SIZE:
            raise DecryptionError("Stored data is too short to be valid")
        nonce, ciphertext = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
        try:
            return self._aead.decrypt(nonce, ciphertext, associated_data)
        except InvalidTag as exc:
            raise DecryptionError("Decryption failed: data altered or wrong key") from exc