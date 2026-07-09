"""Target Label endpoints — kelompokkan Target ke label."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user
from database import get_db
from models import TargetLabel, TargetLabelItem, User
from schemas import TargetLabelAssign, TargetLabelCreate, TargetLabelResponse, TargetLabelUpdate

router = APIRouter(prefix="/api/labels", tags=["Labels"])


def _to_response(label: TargetLabel) -> TargetLabelResponse:
    gids = [it.group_id for it in label.items]
    return TargetLabelResponse(
        id=label.id,
        name=label.name,
        description=label.description,
        color=label.color,
        group_ids=gids,
        count=len(gids),
        created_at=label.created_at,
    )


@router.get("/", response_model=list[TargetLabelResponse])
def list_labels(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # P2: eager-load items supaya _to_response tidak N+1.
    labels = (
        db.query(TargetLabel)
        .options(joinedload(TargetLabel.items))
        .order_by(TargetLabel.name)
        .all()
    )
    return [_to_response(l) for l in labels]


@router.post("/", response_model=TargetLabelResponse)
def create_label(body: TargetLabelCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(TargetLabel).filter(TargetLabel.name == body.name).first():
        raise HTTPException(400, f"Label '{body.name}' sudah ada")
    label = TargetLabel(name=body.name, description=body.description, color=body.color)
    db.add(label)
    db.commit()
    db.refresh(label)
    return _to_response(label)


@router.put("/{label_id}", response_model=TargetLabelResponse)
def update_label(label_id: int, body: TargetLabelUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    label = db.query(TargetLabel).filter(TargetLabel.id == label_id).first()
    if not label:
        raise HTTPException(404, "Label tidak ditemukan")
    for field in ("name", "description", "color"):
        val = getattr(body, field)
        if val is not None:
            setattr(label, field, val)
    db.commit()
    db.refresh(label)
    return _to_response(label)


@router.delete("/{label_id}")
def delete_label(label_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    label = db.query(TargetLabel).filter(TargetLabel.id == label_id).first()
    if not label:
        raise HTTPException(404, "Label tidak ditemukan")
    db.delete(label)
    db.commit()
    return {"message": "Label dihapus"}


@router.post("/{label_id}/assign", response_model=TargetLabelResponse)
def assign_targets(label_id: int, body: TargetLabelAssign, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Set daftar Target untuk label ini (replace)."""
    label = db.query(TargetLabel).filter(TargetLabel.id == label_id).first()
    if not label:
        raise HTTPException(404, "Label tidak ditemukan")
    db.query(TargetLabelItem).filter(TargetLabelItem.label_id == label_id).delete()
    for gid in body.group_ids:
        db.add(TargetLabelItem(label_id=label_id, group_id=gid))
    db.commit()
    db.refresh(label)
    return _to_response(label)
