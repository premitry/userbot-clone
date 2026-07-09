"""Sync folder Telegram (dialog filters) via MTProto — mirror read-only.

Mengambil daftar folder akun (getDialogFilters), menyimpan ke telegram_folders,
lalu resolve tiap peer menjadi target (groups) dan menyimpannya ke
telegram_folder_members. Jika target belum ada di DB, target dibuat dulu.

Desain aman: kegagalan API folder TIDAK merusak Targets yang sudah ada — error
diangkat sebagai RuntimeError dengan pesan jelas dan tidak menghapus data lama.
"""

import json
from datetime import datetime

from database import SessionLocal
from models import Group, TelegramFolder, TelegramFolderMember


def _marked_id(peer):
    """InputPeer -> chat_id gaya Bot API (marked), samakan dengan get_dialogs."""
    uid = getattr(peer, "user_id", None)
    if uid is not None:
        return int(uid)
    cid = getattr(peer, "chat_id", None)
    if cid is not None:
        return -int(cid)
    ch = getattr(peer, "channel_id", None)
    if ch is not None:
        return int("-100" + str(ch))
    return None


def _title_text(title):
    if title is None:
        return ""
    if isinstance(title, str):
        return title
    # Layer baru: TextWithEntities punya atribut .text
    return getattr(title, "text", "") or ""


def _map_type(chat_type) -> str:
    name = getattr(chat_type, "value", str(chat_type)).lower()
    if "supergroup" in name:
        return "supergroup"
    if "channel" in name:
        return "channel"
    if "bot" in name:
        return "bot"
    if "private" in name:
        return "private"
    return "group"


async def _ensure_target(db, client, chat_id, account_id):
    """Cari target by chat_id; jika belum ada, ambil info & buat baru."""
    g = db.query(Group).filter(Group.telegram_id == str(chat_id)).first()
    if g:
        return g

    title = str(chat_id)
    uname = None
    ttype = "group"
    members = 0
    try:
        chat = await client.get_chat(chat_id)
        uname = getattr(chat, "username", None)
        title = (
            getattr(chat, "title", None)
            or getattr(chat, "first_name", None)
            or (("@" + uname) if uname else str(chat_id))
        )
        ttype = _map_type(getattr(chat, "type", "group"))
        members = getattr(chat, "members_count", 0) or 0
    except Exception:
        # Peer tidak bisa di-resolve — tetap simpan sebagai target minimal.
        pass

    g = Group(
        telegram_id=str(chat_id),
        global_unique_key="chat:" + str(chat_id),
        title=title,
        username=uname,
        type=ttype,
        member_count=members,
        can_send=True,
        is_active=True,
        account_id=account_id,
    )
    db.add(g)
    db.flush()
    return g


async def _get_dialog_filters(client):
    """Panggil raw MTProto getDialogFilters (kompatibel beberapa layer)."""
    from pyrogram.raw.functions.messages import GetDialogFilters
    res = await client.invoke(GetDialogFilters())
    # Layer baru: messages.DialogFilters(.filters); layer lama: list langsung
    filters = getattr(res, "filters", None)
    if filters is None:
        filters = res if isinstance(res, list) else []
    return filters


async def sync_telegram_folders(account_id: int) -> dict:
    """Sync semua folder untuk satu akun. Return ringkasan hitungan."""
    from worker.client import get_worker

    worker = get_worker(account_id)
    if not worker or not worker.is_running:
        raise RuntimeError("Akun tidak aktif / worker mati")

    client = worker.client
    try:
        raw_filters = await _get_dialog_filters(client)
    except Exception as e:
        raise RuntimeError("Gagal ambil folder Telegram (getDialogFilters): " + str(e))

    db = SessionLocal()
    new_folders = 0
    total_members = 0
    try:
        for f in raw_filters:
            fid = getattr(f, "id", None)
            if fid is None:
                continue  # DialogFilterDefault (Semua chat) tidak punya id

            pinned = list(getattr(f, "pinned_peers", []) or [])
            include = list(getattr(f, "include_peers", []) or [])
            exclude = list(getattr(f, "exclude_peers", []) or [])
            name = _title_text(getattr(f, "title", "")) or ("Folder " + str(fid))

            inc_ids = []
            for p in (pinned + include):
                mid = _marked_id(p)
                if mid is not None and mid not in inc_ids:
                    inc_ids.append(mid)
            exc_ids = []
            for p in exclude:
                mid = _marked_id(p)
                if mid is not None and mid not in exc_ids:
                    exc_ids.append(mid)

            fol = db.query(TelegramFolder).filter(
                TelegramFolder.account_id == account_id,
                TelegramFolder.folder_id == fid,
            ).first()
            if fol:
                fol.name = name
                fol.title = name
                fol.include_peers_json = json.dumps(inc_ids)
                fol.exclude_peers_json = json.dumps(exc_ids)
                fol.raw_json = str(f)[:4000]
                fol.last_synced_at = datetime.utcnow()
                fol.updated_at = datetime.utcnow()
            else:
                fol = TelegramFolder(
                    account_id=account_id,
                    folder_id=fid,
                    name=name,
                    title=name,
                    include_peers_json=json.dumps(inc_ids),
                    exclude_peers_json=json.dumps(exc_ids),
                    raw_json=str(f)[:4000],
                    last_synced_at=datetime.utcnow(),
                )
                db.add(fol)
                db.flush()
                new_folders += 1

            # Reset anggota lalu isi ulang (mirror penuh dari Telegram)
            db.query(TelegramFolderMember).filter(
                TelegramFolderMember.folder_id == fol.id
            ).delete()
            for mid in inc_ids:
                g = await _ensure_target(db, client, mid, account_id)
                db.add(TelegramFolderMember(folder_id=fol.id, target_id=g.id))
                total_members += 1
            db.commit()

        return {"folders": new_folders, "members": total_members}
    except Exception as e:
        db.rollback()
        raise RuntimeError("Gagal simpan folder: " + str(e))
    finally:
        db.close()
