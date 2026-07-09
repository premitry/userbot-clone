"""
Multi-account Kurigram client manager.
Setiap akun Telegram punya client sendiri.

Penomoran log memakai urutan tampil (1..N) lewat `seq`, bukan account_id di DB,
sehingga kalau akun pertama dihapus, akun berikutnya jadi #1.

session_string disimpan terenkripsi di DB; di-decrypt tepat sebelum dipakai
membangun Client.
"""

import logging
from datetime import datetime
from typing import Optional

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

from config import settings
from crypto import decrypt_session
from database import SessionLocal
from models import BotStatus, TelegramAccount

logger = logging.getLogger("worker.client")

# Store semua active clients: {account_id: BotWorker}
_workers: dict[int, "BotWorker"] = {}


class BotWorker:
    """Satu worker = satu akun Telegram."""

    def __init__(self, account_id: int, session_string: str, seq: Optional[int] = None):
        self.account_id = account_id
        self.seq = seq
        self.client = Client(
            name=f"userbot_{account_id}",
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=decrypt_session(session_string),
            in_memory=True,
        )
        self.is_running = False
        self.display_name = f"Account #{seq if seq else account_id}"

    def _tag(self) -> str:
        return f"#{self.seq}" if self.seq else f"#{self.account_id}"

    async def start(self) -> bool:
        try:
            await self.client.start()
            self.is_running = True

            # Daftarkan handler command (/pay, /qris, dst) untuk akun ini.
            try:
                from worker.command_handler import register_handlers
                register_handlers(self.client, self.account_id)
            except Exception as e:
                logger.warning("Gagal daftar command handler %s: %s", self._tag(), e)

            me = await self.client.get_me()
            name = me.first_name or ""
            uname = me.username or ""
            self.display_name = f"{name} (@{uname})" if uname else name

            db = SessionLocal()
            try:
                account = db.query(TelegramAccount).filter(
                    TelegramAccount.id == self.account_id
                ).first()
                if account:
                    account.username = uname
                    account.first_name = name
                    account.telegram_id = str(me.id)
                    account.is_connected = True
                    account.last_connected = datetime.utcnow()
                    db.commit()
            finally:
                db.close()

            logger.info("Account %s connected: %s", self._tag(), self.display_name)
            return True

        except SessionPasswordNeeded:
            logger.error("Account %s needs 2FA — re-add from dashboard", self._tag())
            self.is_running = False
            return False

        except Exception as e:
            logger.error("Account %s failed: %s", self._tag(), e)
            self.is_running = False
            return False

    async def stop(self):
        try:
            await self.client.stop()
        except Exception:
            pass
        self.is_running = False

        db = SessionLocal()
        try:
            account = db.query(TelegramAccount).filter(
                TelegramAccount.id == self.account_id
            ).first()
            if account:
                account.is_connected = False
                db.commit()
        finally:
            db.close()

        logger.info("Account %s disconnected", self._tag())


def get_worker(account_id: int = None) -> Optional[BotWorker]:
    """Get worker by account_id. If None, return first active worker."""
    if account_id:
        return _workers.get(account_id)

    for w in _workers.values():
        if w.is_running:
            return w
    return None


def get_all_workers() -> dict[int, BotWorker]:
    return _workers


def _resequence():
    """Beri nomor urut 1..N ke worker sesuai urutan account_id (stabil)."""
    for idx, aid in enumerate(sorted(_workers.keys()), start=1):
        _workers[aid].seq = idx


async def start_account(account_id: int, session_string: str, seq: Optional[int] = None) -> bool:
    if account_id in _workers:
        await _workers[account_id].stop()

    worker = BotWorker(account_id, session_string, seq=seq)
    success = await worker.start()

    if success:
        _workers[account_id] = worker
        if seq is None:
            _resequence()
        _update_bot_status()

    return success


async def stop_account(account_id: int):
    if account_id in _workers:
        await _workers[account_id].stop()
        del _workers[account_id]
        _resequence()
        _update_bot_status()


async def init_all_workers():
    if not settings.API_ID or not settings.API_HASH:
        logger.warning("API_ID atau API_HASH kosong! Isi dulu di file .env (https://my.telegram.org)")
        return

    db = SessionLocal()
    try:
        accounts = db.query(TelegramAccount).filter(
            TelegramAccount.is_active == True
        ).order_by(TelegramAccount.id.asc()).all()

        if not accounts:
            logger.info("Belum ada akun Telegram terhubung. Tambah lewat menu Accounts.")
            return

        logger.info("Starting %d account(s)...", len(accounts))

        for idx, acc in enumerate(accounts, start=1):
            await start_account(acc.id, acc.session_string, seq=idx)

    finally:
        db.close()

    _resequence()
    _update_bot_status()


async def shutdown_all_workers():
    for account_id in list(_workers.keys()):
        await stop_account(account_id)


def _update_bot_status():
    active = sum(1 for w in _workers.values() if w.is_running)

    db = SessionLocal()
    try:
        bot = db.query(BotStatus).first()
        if not bot:
            bot = BotStatus(
                is_running=active > 0,
                active_accounts=active,
                uptime_start=datetime.utcnow() if active > 0 else None,
            )
            db.add(bot)
        else:
            bot.is_running = active > 0
            bot.active_accounts = active
            if active > 0 and not bot.uptime_start:
                bot.uptime_start = datetime.utcnow()
            elif active == 0:
                bot.uptime_start = None
            bot.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
