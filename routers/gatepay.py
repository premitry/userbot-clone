"""Router GatePay: per-akun settings + list orders + test connection.

Semua endpoint di-scope ke akun aktif (get_active_account_id).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import PaymentOrder, TelegramAccount, User
from routers.webhooks import DEFAULT_THANKS_TEXT, render_thanks
from schemas import (
    GatePayOrderResponse, GatePaySettings, GatePaySettingsUpdate,
)
from worker.client import get_worker
from worker.gatepay_client import GatePayError, test_connection

router = APIRouter(prefix="/api/gatepay", tags=["GatePay"])


def _require_active(db: Session) -> TelegramAccount:
    aid = get_active_account_id(db)
    if aid is None:
        raise HTTPException(400, "Pilih akun aktif dulu di menu Accounts")
    acc = db.query(TelegramAccount).filter(TelegramAccount.id == aid).first()
    if not acc:
        raise HTTPException(404, "Akun aktif tidak ditemukan")
    return acc


@router.get("/settings", response_model=GatePaySettings)
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acc = _require_active(db)
    return GatePaySettings(
        account_id=acc.id,
        has_api_key=bool(acc.gatepay_api_key),
        has_callback_secret=bool(acc.gatepay_callback_secret),
        api_key_masked=_mask(acc.gatepay_api_key),
        gatepay_notify_on_paid=bool(acc.gatepay_notify_on_paid),
        gatepay_thanks_text=acc.gatepay_thanks_text or "",
        gatepay_expires_in=int(acc.gatepay_expires_in or 0) or 900,
    )


@router.put("/settings", response_model=GatePaySettings)
def update_settings(
    body: GatePaySettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    acc = _require_active(db)
    if body.gatepay_api_key is not None:
        acc.gatepay_api_key = body.gatepay_api_key.strip() or None
    if body.gatepay_callback_secret is not None:
        acc.gatepay_callback_secret = body.gatepay_callback_secret.strip() or None
    if body.gatepay_notify_on_paid is not None:
        acc.gatepay_notify_on_paid = body.gatepay_notify_on_paid
    if body.gatepay_thanks_text is not None:
        acc.gatepay_thanks_text = body.gatepay_thanks_text
    if body.gatepay_expires_in is not None:
        v = int(body.gatepay_expires_in)
        if v < 60 or v > 86400:
            raise HTTPException(400, "expires_in harus antara 60 dan 86400 detik")
        acc.gatepay_expires_in = v
    db.commit()
    db.refresh(acc)
    return get_settings(db, user)


@router.post("/test")
async def test(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    acc = _require_active(db)
    if not acc.gatepay_api_key:
        raise HTTPException(400, "API key GatePay belum diisi")
    try:
        return await test_connection(acc.gatepay_api_key)
    except GatePayError as e:
        raise HTTPException(400, str(e))


@router.get("/defaults")
def get_defaults(user: User = Depends(get_current_user)):
    """Default value untuk field yang bisa dikustom user."""
    return {"thanks_text": DEFAULT_THANKS_TEXT}


class TestThanksBody(BaseModel):
    chat_id: str
    text: str | None = None  # kalau diisi, pakai text ini (preview sebelum simpan)


@router.post("/test-thanks")
async def test_thanks(
    body: TestThanksBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Kirim preview pesan terima kasih ke chat tertentu (untuk memastikan worker aktif)."""
    acc = _require_active(db)
    try:
        chat_id: int | str = int(body.chat_id)
    except (TypeError, ValueError):
        chat_id = (body.chat_id or "").strip()
        if not chat_id:
            raise HTTPException(400, "chat_id wajib diisi (angka atau @username)")

    template = body.text if body.text is not None else acc.gatepay_thanks_text
    msg = render_thanks(template, base_amount=25000, unique_amount=25037, ref="TEST-PREVIEW")

    w = get_worker(acc.id)
    if not w or not w.is_running:
        raise HTTPException(400, "Worker akun aktif belum jalan. Start worker dulu di menu Accounts.")
    try:
        sent = await w.client.send_message(chat_id, msg)
    except Exception as e:
        raise HTTPException(400, f"Gagal kirim: {e}")
    return {"ok": True, "message_id": getattr(sent, "id", None), "preview": msg}




@router.delete("/settings/{field}")
def clear_setting(
    field: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Hapus satu field setting GatePay. field: api_key | callback_secret | thanks_text | all"""
    acc = _require_active(db)
    if field == "api_key":
        acc.gatepay_api_key = None
    elif field == "callback_secret":
        acc.gatepay_callback_secret = None
    elif field == "thanks_text":
        acc.gatepay_thanks_text = None
    elif field == "all":
        acc.gatepay_api_key = None
        acc.gatepay_callback_secret = None
        acc.gatepay_thanks_text = None
        acc.gatepay_notify_on_paid = False
    else:
        raise HTTPException(400, "field tidak dikenal (api_key|callback_secret|thanks_text|all)")
    db.commit()
    return {"message": f"Setting '{field}' dihapus", "field": field}



@router.post("/orders/sync")
async def sync_orders(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cek ulang status order pending/aktif ke GatePay & update DB.

    Berguna kalau order sudah cancelled/expired/paid di sisi GatePay tapi
    webhook nggak nyampe (mis. server down / URL salah).
    """
    from datetime import datetime as _dt
    from worker.gatepay_client import get_order as _get_order

    acc = _require_active(db)
    if not acc.gatepay_api_key:
        raise HTTPException(400, "API key GatePay belum diisi")

    q = (
        db.query(PaymentOrder)
        .filter(PaymentOrder.account_id == acc.id)
        .filter(PaymentOrder.status == "pending")
        .order_by(PaymentOrder.created_at.desc())
        .limit(min(limit, 200))
    )
    orders = q.all()
    updated = 0
    errors: list[str] = []
    for o in orders:
        try:
            data = await _get_order(acc.gatepay_api_key, o.order_id)
        except GatePayError as e:
            # 404 = order sudah hilang di sisi provider → anggap cancelled.
            if getattr(e, "status", 0) == 404:
                o.status = "cancelled"
                updated += 1
                continue
            errors.append(f"{o.order_id}: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            errors.append(f"{o.order_id}: {e}")
            continue

        remote_status = str(data.get("status") or "").lower().strip()
        mapping = {
            "paid": "paid", "success": "paid", "settled": "paid",
            "pending": "pending", "waiting": "pending", "unpaid": "pending",
            "expired": "expired",
            "cancel": "cancelled", "cancelled": "cancelled", "canceled": "cancelled",
            "failed": "failed", "error": "failed",
        }
        new_status = mapping.get(remote_status, o.status)
        newly_paid = False
        if new_status != o.status:
            was_paid = o.status == "paid"
            o.status = new_status
            if new_status == "paid" and not o.paid_at:
                paid_at = data.get("paid_at")
                try:
                    o.paid_at = _dt.utcfromtimestamp(int(paid_at)) if paid_at else _dt.utcnow()
                except Exception:
                    o.paid_at = _dt.utcnow()
            if new_status == "paid" and not was_paid:
                newly_paid = True
            updated += 1
        if newly_paid and acc.gatepay_notify_on_paid:
            import asyncio as _asyncio
            from routers.webhooks import _notify_paid as _notify
            # Worker Pyrogram jalan di loop/thread sendiri. Kalau kita cuma
            # create_task di loop FastAPI, delete/send-nya bakal gagal diam-
            # diam. Jadwalkan di loop worker via run_coroutine_threadsafe.
            w = get_worker(acc.id)
            scheduled = False
            if w and w.is_running:
                wloop = getattr(w.client, "loop", None)
                if wloop is not None:
                    try:
                        _asyncio.run_coroutine_threadsafe(_notify(o, acc), wloop)
                        scheduled = True
                    except Exception as _e:
                        errors.append(f"{o.order_id}: notify schedule: {_e}")
            if not scheduled:
                _asyncio.create_task(_notify(o, acc))

    db.commit()
    return {"ok": True, "checked": len(orders), "updated": updated, "errors": errors}


@router.get("/orders", response_model=list[GatePayOrderResponse])
def list_orders(
    limit: int = 100,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    aid = get_active_account_id(db)
    q = db.query(PaymentOrder)
    if aid is not None:
        q = q.filter(PaymentOrder.account_id == aid)
    if status:
        q = q.filter(PaymentOrder.status == status)
    return q.order_by(PaymentOrder.created_at.desc()).limit(min(limit, 500)).all()


def _mask(s: str | None) -> str:
    if not s:
        return ""
    if len(s) <= 8:
        return "•" * len(s)
    return s[:4] + "•" * (len(s) - 8) + s[-4:]
