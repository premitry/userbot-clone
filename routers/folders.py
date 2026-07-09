"""Telegram Folders — mirror read-only dialog filters + sync via MTProto.

List folder di-scope ke AKUN AKTIF.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import Group, TelegramFolder, TelegramFolderMember, User
from worker.client import get_all_workers
from worker.folder_sync import sync_telegram_folders

router = APIRouter(prefix="/api/folders", tags=["Folders"])


def _target_dict(g):
    return {
        "id": g.id,
        "telegram_id": g.telegram_id,
        "title": g.title,
        "username": g.username,
        "type": g.type,
        "can_send": bool(g.can_send),
        "member_count": g.member_count or 0,
    }


@router.get("/")
def list_folders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    active = get_active_account_id(db)
    q = db.query(TelegramFolder)
    if active is not None:
        q = q.filter(TelegramFolder.account_id == active)
    out = []
    for f in q.order_by(TelegramFolder.name).all():
        cnt = db.query(TelegramFolderMember).filter(
            TelegramFolderMember.folder_id == f.id
        ).count()
        out.append({
            "id": f.id,
            "account_id": f.account_id,
            "folder_id": f.folder_id,
            "name": f.name,
            "title": f.title,
            "count": cnt,
            "last_synced_at": f.last_synced_at.isoformat() if f.last_synced_at else None,
        })
    return out


@router.get("/{fid}/members")
def folder_members(fid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = db.query(TelegramFolder).filter(TelegramFolder.id == fid).first()
    if not f:
        raise HTTPException(404, "Folder tidak ditemukan")
    items = db.query(TelegramFolderMember).filter(
        TelegramFolderMember.folder_id == fid
    ).all()
    ids = [it.target_id for it in items]
    rows = db.query(Group).filter(Group.id.in_(ids)).all() if ids else []
    return [_target_dict(g) for g in rows]


@router.post("/sync")
async def sync_folders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Sync folder dari SEMUA akun aktif. Error per-akun tidak menghentikan lainnya."""
    workers = get_all_workers()
    running = [w for w in workers.values() if w.is_running]
    if not running:
        raise HTTPException(503, "Tidak ada akun Telegram yang aktif")

    total_folders = 0
    total_members = 0
    errors = []
    for w in running:
        try:
            res = await sync_telegram_folders(w.account_id)
            total_folders += res.get("folders", 0)
            total_members += res.get("members", 0)
        except Exception as e:
            errors.append("Akun #" + str(w.account_id) + ": " + str(e))

    msg = (
        "Sync folder selesai dari " + str(len(running)) + " akun. "
        + str(total_folders) + " folder baru, " + str(total_members) + " anggota."
    )
    if errors:
        msg += " Catatan: " + " | ".join(errors)
    return {"message": msg, "errors": errors}
