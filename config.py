"""Application configuration loaded from environment variables.

SECRET_KEY dan ENCRYPTION_KEY WAJIB ada dan TIDAK boleh memakai nilai default
yang lemah. Jika belum diset, keduanya di-generate otomatis (aman) lalu
disimpan permanen ke file .env sekali saja, sehingga aplikasi tetap bisa jalan
tanpa langkah manual.
"""

import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv, set_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("config")

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

_INSECURE_SECRETS = {"", "change-me-please", "changeme", "secret", "please-change"}


def _persist_env(key: str, value: str) -> None:
    """Simpan key=value ke .env (best effort) dan ke environment proses ini."""
    try:
        ENV_PATH.touch(exist_ok=True)
        set_key(str(ENV_PATH), key, value)
    except Exception as e:  # pragma: no cover
        logger.warning("Tidak bisa menyimpan %s ke .env (%s); dipakai sementara.", key, e)
    os.environ[key] = value


def _ensure_secret_key() -> str:
    val = (os.getenv("SECRET_KEY") or "").strip()
    if val in _INSECURE_SECRETS:
        val = secrets.token_urlsafe(48)
        _persist_env("SECRET_KEY", val)
        logger.info("SECRET_KEY di-generate otomatis & disimpan ke .env")
    return val


def _ensure_encryption_key() -> str:
    val = (os.getenv("ENCRYPTION_KEY") or "").strip()
    if not val:
        from cryptography.fernet import Fernet
        val = Fernet.generate_key().decode()
        _persist_env("ENCRYPTION_KEY", val)
        logger.info("ENCRYPTION_KEY di-generate otomatis & disimpan ke .env")
    return val


class Settings:
    # Telegram API (sama untuk semua akun)
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")

    # DEPRECATED: single-account session (legacy, tidak dipakai lagi di kode).
    SESSION_STRING: str = os.getenv("SESSION_STRING", "")

    # App — di-generate otomatis bila belum diset (tidak pernah pakai default lemah).
    SECRET_KEY: str = _ensure_secret_key()
    ENCRYPTION_KEY: str = _ensure_encryption_key()
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./userbot.db")


settings = Settings()
