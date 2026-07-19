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

import asyncio
import hashlib
import hmac
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from database import SessionLocal
from models import PaymentOrder, TelegramAccount

router = APIRouter(prefix="/api/public/webhooks", tags=["Webhooks"])


def _verify(secret: str, raw: bytes, signature: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def _fmt_amount(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


async def _notify_paid(order: PaymentOrder, account: TelegramAccount):
    """Kirim balasan Telegram bahwa pembayaran lunas + (opsional) hapus QR."""
    from worker.client import get_worker
    w = get_worker(account.id)
    if not w or not w.is_running:
        return
    client = w.client

    thanks = (account.gatepay_thanks_text or "").strip() or (
        "✅ Pembayaran diterima, terima kasih! 🙏"
    )
    thanks = thanks.replace("{amount}", _fmt_amount(order.base_amount)).replace(
        "{amount_rp}", "Rp" + _fmt_amount(order.base_amount)
    ).replace("{unique_rp}", "Rp" + _fmt_amount(order.unique_amount)).replace(
        "{ref}", order.reference or ""
    )

    try:
        chat_id = int(order.chat_id) if order.chat_id else None
    except Exception:
        chat_id = None
    if chat_id is None:
        return

    # Hapus pesan QR lama biar rapi (best-effort).
    if order.tg_message_id:
        try:
            await client.delete_messages(chat_id, order.tg_message_id)
        except Exception:
            pass

    reply_to = order.tg_message_id or None
    try:
        await client.send_message(chat_id, thanks, reply_to_message_id=reply_to)
    except Exception:
        try:
            await client.send_message(chat_id, thanks)
        except Exception:
            pass


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

        # Idempotent: kalau sudah paid, skip notif.
        already_paid = order.status == "paid"

        if event == "order.paid":
            order.status = "paid"
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

        db.commit()

        if event == "order.paid" and not already_paid and account.gatepay_notify_on_paid:
            asyncio.create_task(_notify_paid(order, account))

        return {"ok": True}
    finally:
        db.close()
