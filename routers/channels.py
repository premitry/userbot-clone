"""Channel Library — sync postingan channel untuk dipakai forward/copy."""

import random as _random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import ChannelPost, User
from schemas import ChannelPostResponse, ChannelSyncRequest
from worker.client import get_worker

router = APIRouter(prefix="/api/channels", tags=["Channels"])


def _normalize_channel(raw: str):
    c = (raw or "").strip()
    if "t.me/" in c:
        c = c.split("t.me/")[-1].strip("/")
        c = c.split("/")[0]
    if c.startswith("@"):  # username
        return c
    if c.lstrip("-").isdigit():
        return int(c)
    return c


def _post_url(chat_id, username, mid):
    if username:
        return "https://t.me/" + str(username) + "/" + str(mid)
    sid = str(chat_id)
    if sid.startswith("-100"):
        return "https://t.me/c/" + sid[4:] + "/" + str(mid)
    return None


@router.get("/", response_model=list[ChannelPostResponse])
def list_posts(
    channel_chat_id: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ChannelPost)
    if channel_chat_id:
        q = q.filter(ChannelPost.channel_chat_id == channel_chat_id)
    return q.order_by(ChannelPost.tg_message_id.desc()).limit(200).all()


@router.get("/list")
def list_channels(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Daftar channel unik yang sudah di-sync.

    P2: dedup di database via GROUP BY (bukan load semua baris ke memori).
    Satu baris per channel_chat_id; title/username diambil salah satu (MAX).
    """
    rows = (
        db.query(
            ChannelPost.channel_chat_id.label("channel_chat_id"),
            func.max(ChannelPost.channel_title).label("channel_title"),
            func.max(ChannelPost.channel_username).label("channel_username"),
            func.count(ChannelPost.id).label("cnt"),
        )
        .group_by(ChannelPost.channel_chat_id)
        .all()
    )
    return [
        {
            "channel_chat_id": r.channel_chat_id,
            "channel_title": r.channel_title,
            "channel_username": r.channel_username,
            "count": r.cnt,
        }
        for r in rows
    ]


@router.post("/sync")
async def sync_channel(body: ChannelSyncRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Ambil beberapa postingan terakhir dari sebuah channel."""
    worker = get_worker()
    if not worker or not worker.is_running:
        raise HTTPException(503, "Bot worker tidak aktif")

    target = _normalize_channel(body.channel)
    limit = min(max(body.limit or 30, 1), 100)

    try:
        chat = await worker.client.get_chat(target)
        uname = getattr(chat, "username", None)
        title = chat.title or (("@" + uname) if uname else str(chat.id))

        synced = 0
        async for m in worker.client.get_chat_history(chat.id, limit=limit):
            preview = (m.caption or m.text or "")
            preview = preview[:200] if preview else ("[media]" if m.media else "")
            exists = db.query(ChannelPost).filter(
                ChannelPost.channel_chat_id == str(chat.id),
                ChannelPost.tg_message_id == m.id,
            ).first()
            if exists:
                exists.preview = preview
                exists.has_media = bool(m.media)
                exists.synced_at = datetime.utcnow()
                continue
            db.add(ChannelPost(
                channel_chat_id=str(chat.id),
                channel_title=title,
                channel_username=uname,
                tg_message_id=m.id,
                preview=preview,
                has_media=bool(m.media),
                post_url=_post_url(chat.id, uname, m.id),
                posted_at=m.date,
            ))
            synced += 1

        db.commit()
        return {"message": f"Sync '{title}': {synced} postingan baru.", "channel_chat_id": str(chat.id)}

    except Exception as e:
        raise HTTPException(500, f"Gagal sync channel: {e}")


@router.get("/pick")
def pick_post(
    channel_chat_id: str,
    mode: str = "latest",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Pilih 1 post: latest / random."""
    posts = db.query(ChannelPost).filter(
        ChannelPost.channel_chat_id == channel_chat_id
    ).order_by(ChannelPost.tg_message_id.desc()).all()
    if not posts:
        raise HTTPException(404, "Belum ada postingan ter-sync untuk channel ini")
    if mode == "random":
        return posts[_random.randint(0, len(posts) - 1)]
    return posts[0]


@router.delete("/{post_id}")
def delete_post(post_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.query(ChannelPost).filter(ChannelPost.id == post_id).first()
    if not p:
        raise HTTPException(404, "Post tidak ditemukan")
    db.delete(p)
    db.commit()
    return {"message": "Post dihapus"}
