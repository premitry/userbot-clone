"""Enkripsi session string Telegram (Fernet, symmetric).

Session string = kredensial penuh akun Telegram, jadi TIDAK boleh disimpan
plaintext di database. Nilai terenkripsi diberi prefix `enc::v1::` supaya:
  - migrasi transparan: nilai lama tanpa prefix tetap terbaca apa adanya,
  - encrypt_session() idempotent: aman dipanggil berulang.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from config import settings

logger = logging.getLogger("crypto")

SESSION_PREFIX = "enc::v1::"

_fernet = Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt_session(plain: str) -> str:
    """Enkripsi session plaintext -> token berprefix. Idempotent."""
    if not plain or plain.startswith(SESSION_PREFIX):
        return plain
    return SESSION_PREFIX + _fernet.encrypt(plain.encode()).decode()


def decrypt_session(value: str) -> str:
    """Kembalikan session plaintext. Nilai legacy tanpa prefix dikembalikan apa adanya."""
    if not value or not value.startswith(SESSION_PREFIX):
        return value
    token = value[len(SESSION_PREFIX):]
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        logger.error("Gagal decrypt session (ENCRYPTION_KEY berubah?)")
        return ""
