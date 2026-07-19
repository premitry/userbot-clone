"""Router GatePay: per-akun settings + list orders + test connection.

Semua endpoint di-scope ke akun aktif (get_active_account_id).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import PaymentOrder, TelegramAccount, User
from schemas import (
    GatePayOrderResponse, GatePaySettings, GatePaySettingsUpdate,
)
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
