"""Manual Collections — pengelompokan target buatan aplikasi.

List di-scope ke AKUN AKTIF (collection tanpa akun/legacy tetap tampil).
Create otomatis menempel ke akun aktif bila account_id tidak diisi.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import Group, ManualCollection, ManualCollectionMember, User
from schemas import (
    CollectionMemberAction,
    ManualCollectionCreate,
    ManualCollectionResponse,
    ManualCollectionUpdate,
)

router = APIRouter(prefix="/api/collections", tags=["Collections"])


def _to_response(c, db) -> ManualCollectionResponse:
    cnt = db.query(ManualCollectionMember).filter(
        ManualCollectionMember.collection_id == c.id
    ).count()
    return ManualCollectionResponse(
        id=c.id,
        name=c.name,
        description=c.description,
        is_active=bool(c.is_active),
        count=cnt,
        created_at=c.created_at,
    )


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


@router.get("/", response_model=list[ManualCollectionResponse])
def list_collections(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    active = get_active_account_id(db)
    q = db.query(ManualCollection)
    if active is not None:
        q = q.filter(or_(
            ManualCollection.account_id == active,
            ManualCollection.account_id == None,
        ))
    rows = q.order_by(ManualCollection.name).all()
    return [_to_response(c, db) for c in rows]


@router.post("/", response_model=ManualCollectionResponse)
def create_collection(body: ManualCollectionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(ManualCollection).filter(ManualCollection.name == body.name).first():
        raise HTTPException(400, "Collection '" + body.name + "' sudah ada")
    acc_id = body.account_id if body.account_id else get_active_account_id(db)
    c = ManualCollection(
        name=body.name, description=body.description, account_id=acc_id
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_response(c, db)


@router.put("/{cid}", response_model=ManualCollectionResponse)
def update_collection(cid: int, body: ManualCollectionUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.query(ManualCollection).filter(ManualCollection.id == cid).first()
    if not c:
        raise HTTPException(404, "Collection tidak ditemukan")
    for field in ("name", "description", "is_active"):
        val = getattr(body, field)
        if val is not None:
            setattr(c, field, val)
    db.commit()
    db.refresh(c)
    return _to_response(c, db)


@router.delete("/{cid}")
def delete_collection(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.query(ManualCollection).filter(ManualCollection.id == cid).first()
    if not c:
        raise HTTPException(404, "Collection tidak ditemukan")
    db.delete(c)
    db.commit()
    return {"message": "Collection dihapus"}


@router.get("/{cid}/members")
def collection_members(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.query(ManualCollection).filter(ManualCollection.id == cid).first()
    if not c:
        raise HTTPException(404, "Collection tidak ditemukan")
    items = db.query(ManualCollectionMember).filter(
        ManualCollectionMember.collection_id == cid
    ).all()
    ids = [it.target_id for it in items]
    rows = db.query(Group).filter(Group.id.in_(ids)).all() if ids else []
    return [_target_dict(g) for g in rows]


@router.post("/{cid}/members")
def add_members(cid: int, body: CollectionMemberAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.query(ManualCollection).filter(ManualCollection.id == cid).first()
    if not c:
        raise HTTPException(404, "Collection tidak ditemukan")
    existing = {
        m.target_id for m in db.query(ManualCollectionMember).filter(
            ManualCollectionMember.collection_id == cid
        ).all()
    }
    added = 0
    for tid in (body.target_ids or []):
        if tid in existing:
            continue  # cegah duplicate
        db.add(ManualCollectionMember(collection_id=cid, target_id=tid))
        existing.add(tid)
        added += 1
    db.commit()
    return {"message": str(added) + " target ditambahkan", "added": added}


@router.post("/{cid}/members/remove")
def remove_members(cid: int, body: CollectionMemberAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ids = list(body.target_ids or [])
    if ids:
        db.query(ManualCollectionMember).filter(
            ManualCollectionMember.collection_id == cid,
            ManualCollectionMember.target_id.in_(ids),
        ).delete(synchronize_session=False)
        db.commit()
    return {"message": "Target dihapus dari collection"}
