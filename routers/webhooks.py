"""Webhook publik untuk provider payment (GatePay).

Endpoint: POST /api/public/webhooks/gatepay
Verifikasi via header `x-signature` = HMAC-SHA256(raw_body, callback_secret).
Karena setiap akun punya secret sendiri, kita cari akun yang cocok dengan
signature-nya (biasanya cuma satu akun yang match).

Setelah signature valid & event = order.paid:
- Update PaymentOrder.status = 'paid', paid_at
- Trigger reply "lunas" ke chat Telegram asal (via worker akun tsb)
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from database import SessionLocal
from models import PaymentOrder, TelegramAccount

router = APIRouter(prefix="/api/public/webhooks", tags=["Webhooks"])

DEFAULT_THANKS_TEXT = "✅ Pembayaran diterima, terima kasih! 🙏"


def render_thanks(template: str, base_amount: int = 0, unique_amount: int = 0, ref: str = "") -> str:
    text = (template or "").strip() or DEFAULT_THANKS_TEXT
    return (
        text.replace("{amount}", _fmt_amount(base_amount))
            .replace("{amount_rp}", "Rp" + _fmt_amount(base_amount))
            .replace("{unique_rp}", "Rp" + _fmt_amount(unique_amount))
            .replace("{ref}", ref or "")
    )


def _verify(secret: str, raw: bytes, signature: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def _fmt_amount(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


async def _notify_paid(order: PaymentOrder, account: TelegramAccount):
    """Kompatibilitas lama: bersihkan QR + kirim balasan lunas dari order object."""
    return await cleanup_order_telegram(order.order_id, send_thanks=bool(account.gatepay_notify_on_paid))


async def cleanup_order_telegram(order_id: str, send_thanks: bool = False) -> bool:
    """Hapus pesan QR di Telegram dan opsional kirim teks terima kasih.

    Fungsi ini sengaja re-query DB dari `order_id` supaya aman dipanggil setelah
    commit/session close, dan aman dijadwalkan dari loop worker Pyrogram.
    """
    from worker.client import get_worker

    db: Session = SessionLocal()
    try:
        order = db.query(PaymentOrder).filter(PaymentOrder.order_id == order_id).first()
        if not order:
            return False
        account = db.query(TelegramAccount).filter(TelegramAccount.id == order.account_id).first()
        if not account:
            return False

        account_id = account.id
        thanks = render_thanks(
            account.gatepay_thanks_text,
            base_amount=order.base_amount,
            unique_amount=order.unique_amount,
            ref=order.reference or "",
        )
        chat_raw = order.chat_id
        tg_message_id = order.tg_message_id
    finally:
        db.close()

    w = get_worker(account_id)
    if not w or not w.is_running:
        return False
    client = w.client

    try:
        chat_id = int(chat_raw) if chat_raw else None
    except Exception:
        chat_id = None
    if chat_id is None:
        return False

    # Hapus pesan QR lama biar rapi (best-effort).
    if tg_message_id:
        try:
            await client.delete_messages(chat_id, tg_message_id)
        except Exception:
            pass

    if send_thanks:
        try:
            await client.send_message(chat_id, thanks)
        except Exception:
            pass

    db = SessionLocal()
    try:
        saved = db.query(PaymentOrder).filter(PaymentOrder.order_id == order_id).first()
        if saved:
            saved.telegram_cleaned_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
    return True


def schedule_order_telegram_cleanup(order_id: str, account_id: int | None, send_thanks: bool = False) -> bool:
    """Jadwalkan cleanup ke event loop worker agar delete/send Pyrogram benar-benar jalan."""
    import asyncio
    from worker.client import get_worker

    coro = cleanup_order_telegram(order_id, send_thanks=send_thanks)
    w = get_worker(account_id) if account_id else None
    wloop = getattr(getattr(w, "client", None), "loop", None) if w and w.is_running else None
    if wloop is not None:
        try:
            asyncio.run_coroutine_threadsafe(coro, wloop)
            return True
        except Exception:
            coro.close()
            return False
    try:
        asyncio.create_task(coro)
        return True
    except Exception:
        coro.close()
        return False


@router.post("/gatepay")
async def gatepay_webhook(request: Request):
    raw = await request.body()
    signature = (request.headers.get("x-signature") or "").strip()
    if not signature:
        raise HTTPException(401, "missing signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "invalid json")

    order_id = str(payload.get("order_id") or "").strip()
    event = str(payload.get("event") or "").strip()
    if not order_id:
        raise HTTPException(400, "missing order_id")

    db: Session = SessionLocal()
    try:
        order = db.query(PaymentOrder).filter(PaymentOrder.order_id == order_id).first()
        if not order:
            # Bisa jadi order dari sistem lain — abaikan tanpa error 500.
            return {"ok": True, "ignored": "unknown order"}

        account = None
        if order.account_id:
            account = db.query(TelegramAccount).filter(
                TelegramAccount.id == order.account_id
            ).first()
        if not account or not account.gatepay_callback_secret:
            raise HTTPException(401, "no callback secret configured for account")

        if not _verify(account.gatepay_callback_secret, raw, signature):
            raise HTTPException(401, "invalid signature")

        # Idempotent: kalau sudah pernah cleanup Telegram, jangan spam balasan.
        already_cleaned = bool(order.telegram_cleaned_at)
        cleanup_send_thanks = False
        cleanup_needed = False
        cleanup_order_id = order.order_id
        cleanup_account_id = account.id

        if event == "order.paid":
            order.status = "paid"
            cleanup_needed = not already_cleaned
            cleanup_send_thanks = bool(account.gatepay_notify_on_paid)
            if payload.get("unique_amount"):
                try:
                    order.unique_amount = int(payload["unique_amount"])
                except Exception:
                    pass
            if payload.get("paid_at"):
                try:
                    order.paid_at = datetime.utcfromtimestamp(int(payload["paid_at"]))
                except Exception:
                    order.paid_at = datetime.utcnow()
            else:
                order.paid_at = datetime.utcnow()
        elif event in ("order.expired", "order.cancelled"):
            order.status = event.split(".", 1)[1]
            cleanup_needed = not already_cleaned

        db.commit()

        if cleanup_needed:
            schedule_order_telegram_cleanup(
                cleanup_order_id,
                cleanup_account_id,
                send_thanks=cleanup_send_thanks,
            )

        return {"ok": True}
    finally:
        db.close()
