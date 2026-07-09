"""Target management endpoints (dulu Groups).

Mendukung group, supergroup, channel, private, dan bot. Nama tabel tetap
'groups' (= target unik global). Relasi akun<->target ada di account_targets
sehingga target yang sama TIDAK tampil berulang meski banyak akun bergabung.

List target di-scope ke AKUN AKTIF: hanya menampilkan target yang diikuti
akun aktif.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import AccountTarget, Group, TelegramAccount, User
from schemas import AccountTargetInfo, TargetResponse
from worker.client import get_all_workers

router = APIRouter(prefix="/api/groups", tags=["Targets"])


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


def _acc_name(acc, account_id) -> str:
    if not acc:
        return "Account #" + str(account_id)
    if acc.first_name:
        return acc.first_name
    if acc.username:
        return "@" + acc.username
    return "Account #" + str(account_id)


def _to_target(g, accounts_by_id) -> TargetResponse:
    infos = []
    sendable = 0
    last_sync = None
    for r in g.account_targets:
        acc = accounts_by_id.get(r.account_id)
        infos.append(AccountTargetInfo(
            account_id=r.account_id,
            account_name=_acc_name(acc, r.account_id),
            can_send=bool(r.can_send),
            role=r.role,
            is_joined=bool(r.is_joined),
        ))
        if r.can_send and r.is_joined:
            sendable += 1
        if r.last_synced_at and (last_sync is None or r.last_synced_at > last_sync):
            last_sync = r.last_synced_at
    if last_sync is None:
        last_sync = g.updated_at
    return TargetResponse(
        id=g.id,
        telegram_id=g.telegram_id,
        title=g.title,
        username=g.username,
        type=g.type,
        can_send=bool(g.can_send),
        member_count=g.member_count or 0,
        is_active=bool(g.is_active),
        account_count=len(infos),
        sendable_count=sendable,
        accounts=infos,
        joined_at=g.joined_at,
        last_synced_at=last_sync,
    )


@router.get("/", response_model=list[TargetResponse])
def list_groups(
    type: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    active = get_active_account_id(db)
    # P2: eager-load account_targets supaya tidak N+1 saat _to_target().
    q = db.query(Group).options(joinedload(Group.account_targets))
    if type:
        q = q.filter(Group.type == type)
    if active is not None:
        q = q.join(
            AccountTarget, AccountTarget.target_id == Group.id
        ).filter(AccountTarget.account_id == active)
    groups = q.order_by(Group.title).all()
    accounts_by_id = {a.id: a for a in db.query(TelegramAccount).all()}
    return [_to_target(g, accounts_by_id) for g in groups]


@router.get("/{group_id}/accounts", response_model=list[AccountTargetInfo])
def target_accounts(group_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    g = (
        db.query(Group)
        .options(joinedload(Group.account_targets))
        .filter(Group.id == group_id)
        .first()
    )
    if not g:
        raise HTTPException(404, "Target tidak ditemukan")
    accounts_by_id = {a.id: a for a in db.query(TelegramAccount).all()}
    out = []
    for r in g.account_targets:
        acc = accounts_by_id.get(r.account_id)
        out.append(AccountTargetInfo(
            account_id=r.account_id,
            account_name=_acc_name(acc, r.account_id),
            can_send=bool(r.can_send),
            role=r.role,
            is_joined=bool(r.is_joined),
        ))
    return out


@router.post("/sync")
async def sync_groups(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Sync dialog dari SEMUA akun aktif, dedup target by chat_id ke account_targets."""
    workers = get_all_workers()
    running = [w for w in workers.values() if w.is_running]
    if not running:
        raise HTTPException(503, "Tidak ada akun Telegram yang aktif")

    new_targets = 0
    new_links = 0
    total = 0
    try:
        for w in running:
            acc_id = w.account_id
            async for dialog in w.client.get_dialogs():
                chat = dialog.chat
                if not chat:
                    continue
                total += 1
                ttype = _map_type(chat.type)
                title = (
                    chat.title
                    or getattr(chat, "first_name", None)
                    or (("@" + chat.username) if getattr(chat, "username", None) else "Unknown")
                )
                members = getattr(chat, "members_count", 0) or 0
                uname = getattr(chat, "username", None)

                is_creator = bool(getattr(chat, "is_creator", False))
                is_admin = bool(getattr(chat, "is_admin", False))
                role = "creator" if is_creator else ("admin" if is_admin else "member")
                can_send = True
                if ttype == "channel":
                    can_send = is_creator or is_admin

                key = "chat:" + str(chat.id)
                g = db.query(Group).filter(Group.telegram_id == str(chat.id)).first()
                if g:
                    g.title = title
                    g.username = uname
                    g.type = ttype
                    g.member_count = members
                    if not g.global_unique_key:
                        g.global_unique_key = key
                    if can_send:
                        g.can_send = True
                    g.is_active = True
                    g.updated_at = datetime.utcnow()
                else:
                    g = Group(
                        telegram_id=str(chat.id),
                        global_unique_key=key,
                        title=title,
                        username=uname,
                        type=ttype,
                        member_count=members,
                        can_send=can_send,
                        is_active=True,
                        account_id=acc_id,
                    )
                    db.add(g)
                    db.flush()
                    new_targets += 1

                rel = db.query(AccountTarget).filter(
                    AccountTarget.account_id == acc_id,
                    AccountTarget.target_id == g.id,
                ).first()
                if rel:
                    rel.can_send = can_send
                    rel.role = role
                    rel.is_joined = True
                    rel.last_synced_at = datetime.utcnow()
                else:
                    db.add(AccountTarget(
                        account_id=acc_id,
                        target_id=g.id,
                        can_send=can_send,
                        role=role,
                        is_joined=True,
                    ))
                    new_links += 1
            db.commit()

        return {
            "message": "Sync selesai dari " + str(len(running)) + " akun. "
            + str(new_targets) + " target baru, " + str(new_links)
            + " relasi akun baru (total " + str(total) + " dialog diperiksa)."
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    g = db.query(Group).filter(Group.id == group_id).first()
    if not g:
        raise HTTPException(404, "Target tidak ditemukan")
    db.delete(g)
    db.commit()
    return {"message": "Target dihapus"}
