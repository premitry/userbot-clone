"""Media Library — upload sekali, pakai berkali-kali."""

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import MediaLibrary, User
from schemas import MediaLibraryResponse

router = APIRouter(prefix="/api/media", tags=["Media"])

UPLOAD_DIR = "static/uploads"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def _kind_from_mime(mime: str) -> str:
    m = (mime or "").lower()
    if m.startswith("image/"):
        return "photo"
    if m.startswith("video/"):
        return "video"
    return "document"


@router.get("/", response_model=list[MediaLibraryResponse])
def list_media(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(MediaLibrary).order_by(MediaLibrary.created_at.desc()).all()


@router.post("/upload", response_model=MediaLibraryResponse)
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

    kind = _kind_from_mime(file.content_type)
    item = MediaLibrary(
        name=file.filename or fname,
        url=f"/static/uploads/{fname}",
        kind=kind,
        mime_type=file.content_type,
        size=len(data),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{media_id}")
def delete_media(media_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(MediaLibrary).filter(MediaLibrary.id == media_id).first()
    if not item:
        raise HTTPException(404, "Media tidak ditemukan")
    # hapus file fisik kalau ada
    try:
        local = item.url.lstrip("/") if item.url.startswith("/static/") else None
        if local and os.path.exists(local):
            os.remove(local)
    except Exception:
        pass
    db.delete(item)
    db.commit()
    return {"message": "Media dihapus"}
