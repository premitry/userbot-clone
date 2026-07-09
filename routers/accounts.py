"""
Telegram account management — add/remove accounts via web.
Support: QR Code login, Phone+OTP, Session String, 2FA.
Juga menyimpan 'akun aktif' untuk scope command/target/dll per-akun.
"""

import asyncio
import base64
import io
from datetime import datetime
from typing import Optional

import qrcode
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    PasswordHashInvalid,
    AuthTokenExpired,
)
from pyrogram.qrlogin import QRLogin

from active_account import get_active_account_id, set_active_account_id
from auth import get_current_user
from config import settings
from database import get_db
from models import TelegramAccount, User
from schemas import (
    AccountAddPhone, AccountAddSession, ActiveAccountSet,
    AccountResponse, AccountVerify2FA, AccountVerifyOTP,
)
from worker.client import get_all_workers, start_account, stop_account

router = APIRouter(prefix="/api/accounts", tags=["Accounts"])

# Temporary storage for login flows (in-memory, per session)
_login_sessions: dict[str, dict] = {}


def _qr_data_url(text: str) -> str:
    """Render QR jadi PNG base64 data URL (tidak bergantung library JS di browser)."""
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


async def _safe_disconnect(client: Client) -> None:
    """Tutup client yang dibuka via connect(), aman dari double-terminate."""
    try:
        await client.disconnect()
    except Exception:
        pass


# ── List & Delete ──────────────────
@router.get("/", response_model=list[AccountResponse])
def list_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    accounts = db.query(TelegramAccount).order_by(
        TelegramAccount.added_at.desc()
    ).all()

    # Update is_connected from live workers
    workers = get_all_workers()
    for acc in accounts:
        w = workers.get(acc.id)
        acc.is_connected = w.is_running if w else False

    return accounts


# ── Akun aktif (scope per-akun) ──
@router.get("/active")
def get_active_account(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Kembalikan id akun aktif saat ini (null jika belum ada akun)."""
    return {"account_id": get_active_account_id(db)}


@router.post("/active")
def set_active_account(
    data: ActiveAccountSet,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Set akun aktif. Command/target/dll akan mengikuti akun ini."""
    result = set_active_account_id(db, data.account_id)
    if result is None:
        raise HTTPException(404, "Akun tidak ditemukan")
    return {"account_id": result}


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(
        TelegramAccount.id == account_id
    ).first()
    if not account:
        raise HTTPException(404, "Akun tidak ditemukan")

    await stop_account(account_id)
    db.delete(account)
    db.commit()
    return {"message": f"Akun {account.first_name or account.phone} dihapus"}


@router.post("/{account_id}/toggle")
async def toggle_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = db.query(TelegramAccount).filter(
        TelegramAccount.id == account_id
    ).first()
    if not account:
        raise HTTPException(404, "Akun tidak ditemukan")

    workers = get_all_workers()
    w = workers.get(account_id)

    if w and w.is_running:
        await stop_account(account_id)
        account.is_active = False
        db.commit()
        return {"message": "Akun dinonaktifkan", "is_active": False}
    else:
        account.is_active = True
        db.commit()
        success = await start_account(account_id, account.session_string)
        if success:
            return {"message": "Akun diaktifkan", "is_active": True}
        else:
            raise HTTPException(500, "Gagal connect akun")


# ── Add via Session String (simple) ──
@router.post("/add-session")
async def add_via_session(
    data: AccountAddSession,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Tambah akun dengan session string yang sudah di-generate."""
    try:
        client = Client(
            name="verify_session",
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            session_string=data.session_string,
            in_memory=True,
            no_updates=True,
        )
        await client.start()
        me = await client.get_me()
        session_str = await client.export_session_string()
        await client.stop()

    except Exception as e:
        raise HTTPException(400, f"Session string tidak valid: {e}")

    existing = db.query(TelegramAccount).filter(
        TelegramAccount.telegram_id == str(me.id)
    ).first()
    if existing:
        raise HTTPException(409, f"Akun @{me.username or me.id} sudah terdaftar")

    account = TelegramAccount(
        phone=me.phone_number,
        username=me.username,
        first_name=me.first_name,
        telegram_id=str(me.id),
        session_string=session_str,
        is_active=True,
        is_connected=False,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    await start_account(account.id, account.session_string)

    return {
        "message": f"Akun @{me.username or me.first_name} berhasil ditambahkan!",
        "account_id": account.id,
    }


# ── Add via Phone + OTP ──
@router.post("/send-code")
async def send_code(
    data: AccountAddPhone,
    user: User = Depends(get_current_user),
):
    """Step 1: Kirim OTP ke nomor telepon."""
    try:
        client = Client(
            name=f"login_{data.phone}",
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            in_memory=True,
            no_updates=True,
        )
        await client.connect()
        sent = await client.send_code(data.phone)

        _login_sessions[data.phone] = {
            "client": client,
            "phone_code_hash": sent.phone_code_hash,
        }

        return {
            "message": f"Kode OTP dikirim ke {data.phone}",
            "phone_code_hash": sent.phone_code_hash,
        }

    except Exception as e:
        raise HTTPException(400, f"Gagal kirim kode: {e}")


@router.post("/verify-code")
async def verify_code(
    data: AccountVerifyOTP,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Step 2: Verifikasi OTP. Bisa return needs_2fa=true."""
    session = _login_sessions.get(data.phone)
    if not session:
        raise HTTPException(400, "Sesi login tidak ditemukan. Kirim kode ulang.")

    client: Client = session["client"]

    try:
        await client.sign_in(
            data.phone, data.phone_code_hash, data.code,
        )
    except PhoneCodeInvalid:
        raise HTTPException(400, "Kode OTP salah")
    except PhoneCodeExpired:
        _login_sessions.pop(data.phone, None)
        raise HTTPException(400, "Kode OTP expired. Kirim ulang.")
    except SessionPasswordNeeded:
        return {"needs_2fa": True, "message": "Akun ini punya 2FA password"}

    return await _finish_login(client, data.phone, db)


@router.post("/verify-2fa")
async def verify_2fa(
    data: AccountVerify2FA,
    phone: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Step 3 (jika perlu): Verifikasi 2FA password."""
    session = None
    phone_key = ""
    for k, v in _login_sessions.items():
        session = v
        phone_key = k
        break

    if not session:
        raise HTTPException(400, "Sesi login tidak ditemukan")

    client: Client = session["client"]

    try:
        await client.check_password(data.password)
    except PasswordHashInvalid:
        raise HTTPException(400, "Password 2FA salah")

    return await _finish_login(client, phone_key, db)


async def _finish_login(client: Client, phone: str, db: Session) -> dict:
    """Finalize login: save account to database and start worker."""
    me = await client.get_me()
    session_str = await client.export_session_string()

    _login_sessions.pop(phone, None)

    existing = db.query(TelegramAccount).filter(
        TelegramAccount.telegram_id == str(me.id)
    ).first()
    if existing:
        await _safe_disconnect(client)
        raise HTTPException(409, f"Akun @{me.username or me.id} sudah terdaftar")

    await _safe_disconnect(client)

    account = TelegramAccount(
        phone=me.phone_number or phone,
        username=me.username,
        first_name=me.first_name,
        telegram_id=str(me.id),
        session_string=session_str,
        is_active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    await start_account(account.id, account.session_string)

    return {
        "message": f"\u2705 Akun @{me.username or me.first_name} berhasil ditambahkan!",
        "account_id": account.id,
        "name": me.first_name,
        "username": me.username,
    }


# ── QR Code Login helper ──
#
# Kurigram 2.2.23 sudah menyediakan kelas QRLogin bawaan yang menangani
# ExportLoginToken -> ImportLoginToken, migrasi data center, dan token
# refresh secara internal. Jadi kita TIDAK lagi membangun Auth/Session
# secara manual (signature-nya berubah antar versi dan bikin error
# "Auth.__init__() missing ... 'port' and 'test_mode'").


async def _qr_cleanup(client: Client) -> None:
    """Stop dispatcher & disconnect client dengan aman."""
    try:
        await client.dispatcher.stop()
    except Exception:
        pass
    try:
        await client.disconnect()
    except Exception:
        pass


# ── QR Code Login via WebSocket ──
@router.websocket("/qr-login")
async def qr_login_ws(websocket: WebSocket, db: Session = Depends(get_db)):
    """WebSocket endpoint untuk QR Code login (pakai QRLogin bawaan kurigram)."""
    await websocket.accept()

    await websocket.send_json({
        "type": "status",
        "message": "Menghubungkan ke Telegram...",
    })

    client = Client(
        name="qr_login",
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        in_memory=True,
    )

    signed_in = None

    try:
        await client.connect()

        qr = QRLogin(client)
        await qr.recreate()

        await websocket.send_json({
            "type": "status",
            "message": "Membuat QR code...",
        })

        while signed_in is None:
            # Tampilkan (atau refresh) QR token ke frontend
            await websocket.send_json({
                "type": "qr_url",
                "url": qr.url,
                "image": _qr_data_url(qr.url),
                "message": "Scan: Telegram HP -> Settings -> Devices -> Link Desktop Device",
            })

            try:
                signed_in = await qr.wait(timeout=30)
            except asyncio.TimeoutError:
                # QR belum discan sampai timeout -> buat token baru
                await qr.recreate()
                continue
            except AuthTokenExpired:
                await qr.recreate()
                continue
            except SessionPasswordNeeded:
                # Akun punya 2FA -> minta password dari frontend
                await websocket.send_json({
                    "type": "status",
                    "message": "QR ter-scan, akun ini butuh 2FA...",
                })
                while signed_in is None:
                    await websocket.send_json({
                        "type": "need_2fa",
                        "message": "Akun ini punya 2FA password. Masukkan password:",
                    })
                    data = await websocket.receive_json()
                    password = data.get("password", "")
                    try:
                        signed_in = await client.check_password(password)
                    except PasswordHashInvalid:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Password 2FA salah!",
                        })
                break

            if signed_in is not None:
                break

            await websocket.send_json({
                "type": "status",
                "message": "QR ter-scan, menyelesaikan login...",
            })

    except WebSocketDisconnect:
        await _qr_cleanup(client)
        return

    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        await _qr_cleanup(client)
        try:
            await websocket.close()
        except Exception:
            pass
        return

    # ── Login berhasil -> simpan akun ──
    try:
        me = await client.get_me()
        session_str = await client.export_session_string()

        existing = db.query(TelegramAccount).filter(
            TelegramAccount.telegram_id == str(me.id)
        ).first()
        if existing:
            await _qr_cleanup(client)
            await websocket.send_json({
                "type": "error",
                "message": f"Akun @{me.username or me.id} sudah terdaftar",
            })
            await websocket.close()
            return

        await _qr_cleanup(client)

        account = TelegramAccount(
            phone=me.phone_number,
            username=me.username,
            first_name=me.first_name,
            telegram_id=str(me.id),
            session_string=session_str,
            is_active=True,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        await start_account(account.id, account.session_string)

        await websocket.send_json({
            "type": "success",
            "message": f"\u2705 Akun @{me.username or me.first_name} berhasil ditambahkan!",
            "account": {
                "id": account.id,
                "name": me.first_name,
                "username": me.username,
            },
        })

    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass

    await websocket.close()
