"""Custom command (Message) management + workflow steps + media/QRIS upload.

Command di-scope PER-AKUN aktif: list hanya menampilkan command milik akun
aktif, create otomatis menempel ke akun aktif, dan cek duplikat command hanya
berlaku dalam lingkup akun yang sama (command sama boleh ada di akun berbeda).
"""

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import MediaLibrary, Message, User, WorkflowStep
from schemas import MessageCreate, MessageResponse, MessageUpdate
from worker.qris_gen import validate_qris_payload

router = APIRouter(prefix="/api/messages", tags=["Messages"])

UPLOAD_DIR = "static/uploads"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _kind_from_mime(mime: str) -> str:
    m = (mime or "").lower()
    if m.startswith("image/"):
        return "photo"
    if m.startswith("video/"):
        return "video"
    return "document"


def _normalize(cmd: str) -> str:
    cmd = (cmd or "").strip().lower()
    if not cmd:
        raise HTTPException(400, "Command tidak boleh kosong")
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    return cmd.split()[0]


def _save_steps(db: Session, message_id: int, steps):
    db.query(WorkflowStep).filter(WorkflowStep.message_id == message_id).delete()
    for i, s in enumerate(steps or []):
        db.add(WorkflowStep(
            message_id=message_id,
            position=i,
            step_type=s.step_type,
            content=s.content,
            media_url=s.media_url,
            channel_post_url=s.channel_post_url,
            delay_seconds=s.delay_seconds or 0,
        ))


@router.get("/", response_model=list[MessageResponse])
def list_messages(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    active = get_active_account_id(db)
    q = db.query(Message)
    if active is not None:
        q = q.filter(Message.account_id == active)
    return q.order_by(Message.command).all()


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File terlalu besar (maks 50MB)")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(data)
    url = f"/static/uploads/{fname}"
    # Catat ke Media Library supaya file yang diupload dari modal command
    # otomatis terbaca di tab Media (auto-read).
    try:
        item = MediaLibrary(
            name=file.filename or fname,
            url=url,
            kind=_kind_from_mime(file.content_type),
            mime_type=file.content_type,
            size=len(data),
        )
        db.add(item)
        db.commit()
    except Exception:
        db.rollback()
    return {"url": url, "filename": file.filename}


@router.post("/decode-qris")
async def decode_qris(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """Baca payload EMVCo dari gambar QRIS statis yang diupload."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File terlalu besar (maks 50MB)")
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    tmp = os.path.join("/tmp", f"{uuid.uuid4().hex}{ext}")
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        from worker.qris_gen import decode_qris_from_image
        payload = decode_qris_from_image(tmp)
        payload = validate_qris_payload(payload)
    except Exception as e:
        raise HTTPException(400, f"Gagal decode QRIS dari gambar: {e}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return {"payload": payload}


@router.post("/", response_model=MessageResponse)
def create_message(body: MessageCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cmd = _normalize(body.command)
    qris_payload = body.qris_payload
    if qris_payload:
        try:
            qris_payload = validate_qris_payload(qris_payload)
        except ValueError as e:
            raise HTTPException(400, str(e))
    active = get_active_account_id(db)
    dup = db.query(Message).filter(
        Message.command == cmd, Message.account_id == active
    ).first()
    if dup:
        raise HTTPException(400, f"Command {cmd} sudah ada di akun ini")
    m = Message(
        account_id=active,
        command=cmd,
        name=body.name,
        type=body.type,
        action=body.action,
        content=body.content,
        media_url=body.media_url,
        channel_post_url=body.channel_post_url,
        channel_mode=body.channel_mode or "specific",
        channel_chat_id=body.channel_chat_id,
        qris_payload=qris_payload,
        qris_min=body.qris_min,
        qris_max=body.qris_max,
        qris_auto_delete_seconds=body.qris_auto_delete_seconds or 0,
        qris_footer_text=body.qris_footer_text,
        is_active=True if body.is_active is None else body.is_active,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    if body.steps is not None:
        _save_steps(db, m.id, body.steps)
        db.commit()
        db.refresh(m)
    return m


@router.put("/{message_id}", response_model=MessageResponse)
def update_message(message_id: int, body: MessageUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.query(Message).filter(Message.id == message_id).first()
    if not m:
        raise HTTPException(404, "Message tidak ditemukan")
    if body.command is not None:
        cmd = _normalize(body.command)
        dup = db.query(Message).filter(
            Message.command == cmd,
            Message.account_id == m.account_id,
            Message.id != message_id,
        ).first()
        if dup:
            raise HTTPException(400, f"Command {cmd} sudah ada di akun ini")
        m.command = cmd
    qris_payload = body.qris_payload
    if qris_payload:
        try:
            qris_payload = validate_qris_payload(qris_payload)
        except ValueError as e:
            raise HTTPException(400, str(e))
    for field in ("name", "type", "action", "content", "media_url", "channel_post_url",
                  "channel_mode", "channel_chat_id", "qris_payload", "qris_min", "qris_max",
                  "qris_auto_delete_seconds", "qris_footer_text", "is_active"):
        val = getattr(body, field)
        if field == "qris_payload" and val is not None:
            val = qris_payload
        if val is not None:
            setattr(m, field, val)
    m.updated_at = datetime.utcnow()
    if body.steps is not None:
        _save_steps(db, m.id, body.steps)
    db.commit()
    db.refresh(m)
    return m


@router.delete("/{message_id}")
def delete_message(message_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.query(Message).filter(Message.id == message_id).first()
    if not m:
        raise HTTPException(404, "Message tidak ditemukan")
    db.delete(m)
    db.commit()
    return {"message": "deleted"}


@router.put("/{message_id}/toggle", response_model=MessageResponse)
def toggle_message(message_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.query(Message).filter(Message.id == message_id).first()
    if not m:
        raise HTTPException(404, "Message tidak ditemukan")
    m.is_active = not m.is_active
    db.commit()
    db.refresh(m)
    return m
