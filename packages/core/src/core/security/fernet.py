"""Fernet encryption for secrets stored at rest (e.g. LLM provider API keys, bucket credentials).

Requires the ``SECRETS_ENCRYPTION_KEY`` environment variable (or
``.env`` file) to be set.
Generate a key with: ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``
"""

import logging

from cryptography.fernet import Fernet

from core.config import get_settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    key = get_settings().secrets_encryption_key
    if not key:
        raise RuntimeError(
            "SECRETS_ENCRYPTION_KEY is not configured. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
            " and add it to your .env file."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string using Fernet symmetric encryption.

    Returns a base64-encoded ciphertext string.
    """
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted string back to plaintext.

    Raises ``cryptography.fernet.InvalidToken`` if the ciphertext is
    malformed or was encrypted with a different key.
    """
    f = _get_fernet()
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
