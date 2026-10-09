"""
Encryption utilities for sensitive data stored at rest.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) with
a dedicated ``FIELD_ENCRYPTION_KEY`` so that rotating Django's
``SECRET_KEY`` does not invalidate encrypted data.
"""

import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)

# Prefix added to every encrypted value so we can distinguish encrypted
# from plaintext data (important during migration and as a safety guard
# against double-encryption).
_ENCRYPTED_PREFIX = "enc:1:"


def _get_fernet() -> Fernet:
    """Return a Fernet instance keyed by ``FIELD_ENCRYPTION_KEY``."""
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise ValueError(
            "FIELD_ENCRYPTION_KEY is not set. "
            "Add a Fernet-compatible base64 key to your .env file."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* and return a prefixed ciphertext string.

    Already-encrypted values (detected by the prefix) are returned as-is
    to prevent double-encryption.
    """
    if not plaintext:
        return plaintext
    if plaintext.startswith(_ENCRYPTED_PREFIX):
        return plaintext  # already encrypted
    ciphertext = _get_fernet().encrypt(plaintext.encode()).decode()
    return f"{_ENCRYPTED_PREFIX}{ciphertext}"


def decrypt_value(value: str) -> str:
    """Decrypt a prefixed ciphertext string.

    If *value* is not prefixed (i.e. still plaintext), it is returned
    unchanged — this allows graceful handling during data migration.
    """
    if not value:
        return value
    if not value.startswith(_ENCRYPTED_PREFIX):
        return value  # plaintext — not yet encrypted
    try:
        ciphertext = value[len(_ENCRYPTED_PREFIX) :]
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        logger.error("Failed to decrypt value: %s", exc)
        return ""  # return empty string to avoid leaking ciphertext


def hash_value(plaintext: str) -> str:
    """Return the SHA-256 hex digest of *plaintext*.

    Used for indexed lookups on encrypted fields (since encrypted values
    are non-deterministic and cannot be searched directly).
    """
    if not plaintext:
        return ""
    return hashlib.sha256(plaintext.encode()).hexdigest()
