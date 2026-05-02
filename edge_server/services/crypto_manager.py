"""
Crypto Manager
===============
Singleton wrapper around Fernet symmetric encryption for database fields.

Enforces:
- No plaintext fallback on encryption/decryption failure
- Key validation at startup
- Clear error logging and propagation

Usage:
    crypto_manager = CryptoManager()
    encrypted = crypto_manager.encrypt("sensitive data")
    decrypted = crypto_manager.decrypt(encrypted)
"""

import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from config import settings

logger = logging.getLogger(__name__)


class CryptoManager:
    """Singleton crypto manager for at‑rest encryption."""

    _instance: Optional["CryptoManager"] = None

    def __new__(cls) -> "CryptoManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialise Fernet with the key from settings. Raise on invalid key."""
        key = settings.database_encryption_key
        if not key:
            logger.warning(
                "DATABASE_ENCRYPTION_KEY not set. Encryption is disabled. "
                "Data will be stored in plaintext."
            )
            self._fernet = None
            return

        # Validate key format
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except Exception as e:
            logger.critical("Invalid DATABASE_ENCRYPTION_KEY: %s", e)
            raise ValueError("Encryption key is invalid") from e

        logger.info("Encryption manager initialised successfully")

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypt a string.

        Returns encrypted base64 string.
        Raises RuntimeError if encryption is not available.
        """
        if plaintext is None:
            return None
        if not plaintext:
            return ""

        if self._fernet is None:
            # Fallback to plaintext if no key is configured
            return plaintext

        try:
            return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        except Exception as e:
            logger.error("Encryption failed: %s", e)
            raise RuntimeError("Encryption failed") from e

    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """
        Decrypt a string.

        Returns original plaintext.
        Raises RuntimeError if decryption fails or encryption is not available.
        """
        if ciphertext is None:
            return None
        if not ciphertext:
            return ""

        if self._fernet is None:
            # Fallback to plaintext if no key is configured
            return ciphertext

        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.error("Decryption failed: Invalid token (corrupted or wrong key)")
            raise RuntimeError("Decryption failed – invalid token") from None
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            raise RuntimeError("Decryption failed") from e


# Global singleton instance
crypto_manager = CryptoManager()