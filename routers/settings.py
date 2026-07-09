"""App settings + admin credential management."""

import io
import os
import uuid

from fastapi import (
    APIRouter, Depends, File, HTTPException, Response, UploadFile,
)
from sqlalchemy.orm import Session

from auth import (
    get_current_user, verify_password, hash_password, create_access_token,
)
from database import get_db
from models import AppSetting, User
from schemas import SettingsUpdate, ChangePassword, ChangeUsername

router = APIRouter(prefix="/api/settings", tags=["Settings"])

SETTING_KEYS = [
    "qris_base_payload", "app_name", "favicon_url",
    "accent_color", "default_language",
    "qris_dynamic_amount", "qris_support_short",
]

# Default value tiap setting (dipakai bila belum pernah di-set).
_DEFAULTS = {
    "qris_base_payload": "",
    "app_name": "",
    "favicon_url": "",
    "accent_color": "",
    "default_language": "id",
    "qris_dynamic_amount": "1",
    "qris_support_short": "1",
}

UPLOAD_DIR = "static/uploads"
FAVICON_EXT = (".png", ".jpg", ".jpeg", ".ico", ".svg", ".webp", ".gif")


def _get(db, key, default=""):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row and row.value is not None else default


def _set(db, key, value):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def _all(db):
    return {k: _get(db, k, _DEFAULTS.get(k, "")) for k in SETTING_KEYS}


@router.get("/")
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _all(db)


@router.put("/")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.qris_base_payload is not None:
        _set(db, "qris_base_payload", body.qris_base_payload.strip())
    if body.app_name is not None:
        _set(db, "app_name", body.app_name.strip())
    if body.accent_color is not None:
        _set(db, "accent_color", body.accent_color.strip())
    if body.default_language is not None:
        _set(db, "default_language", body.default_language.strip())
    if body.qris_dynamic_amount is not None:
        _set(db, "qris_dynamic_amount", "1" if body.qris_dynamic_amount else "0")
    if body.qris_support_short is not None:
        _set(db, "qris_support_short", "1" if body.qris_support_short else "0")
    db.commit()
    return _all(db)


@router.post("/favicon-upload")
async def favicon_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload favicon -> simpan file -> simpan url ke settings."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "File kosong")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "Favicon terlalu besar (maks 2MB)")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in FAVICON_EXT:
        ext = ".png"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = "favicon_" + uuid.uuid4().hex[:8] + ext
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    url = "/static/uploads/" + name
    _set(db, "favicon_url", url)
    db.commit()
    return {"favicon_url": url, "message": "Favicon tersimpan"}


@router.post("/qris-upload")
async def qris_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload gambar QRIS -> decode QR jadi payload teks -> simpan sebagai base payload.

    Endpoint tetap tersedia untuk kompatibilitas / QRIS per-command,
    walau kartu upload global sudah dihapus dari halaman Settings.
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "File kosong")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Gambar terlalu besar (maks 5MB)")
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode as qr_decode
    except Exception:
        raise HTTPException(
            500,
            "Library QR belum terpasang di server. Jalankan: apt install libzbar0 && pip install -r requirements.txt",
        )
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(400, "Gambar tidak valid / tidak bisa dibaca")
    codes = qr_decode(img)
    if not codes:
        raise HTTPException(400, "QR code tidak terdeteksi. Pastikan gambar QRIS jelas & tidak terpotong.")
    payload = codes[0].data.decode("utf-8", errors="ignore").strip()
    if not payload:
        raise HTTPException(400, "Isi QR kosong / tidak terbaca")
    _set(db, "qris_base_payload", payload)
    db.commit()
    return {"qris_base_payload": payload, "message": "QRIS berhasil di-decode"}


@router.post("/change-password")
def change_password(body: ChangePassword, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Password lama salah")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Password baru minimal 6 karakter")
    user.password_hash = hash_password(body.new_password)
    # Lunas: hapus paksaan ganti password (mis. setelah login pertama admin).
    user.must_change_password = False
    db.commit()
    return {"message": "Password berhasil diganti"}


@router.post("/change-username")
def change_username(body: ChangeUsername, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Password salah")
    new_username = body.new_username.strip()
    if len(new_username) < 3:
        raise HTTPException(400, "Username minimal 3 karakter")
    dup = db.query(User).filter(User.username == new_username, User.id != user.id).first()
    if dup:
        raise HTTPException(400, "Username sudah dipakai")
    user.username = new_username
    db.commit()
    token = create_access_token(data={"sub": new_username})
    response.set_cookie(key="access_token", value=token, httponly=True, max_age=86400, samesite="lax")
    return {"message": "Username berhasil diganti", "username": new_username}
