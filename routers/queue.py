"""Queue endpoints — monitor & kontrol antrian Auto Share.

List job di-scope ke AKUN AKTIF berdasarkan akun pemilik campaign (Schedule).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import QueueJob, Schedule, User
from schemas import QueueAction, QueueJobResponse

router = APIRouter(prefix="/api/queue", tags=["Queue"])


@router.get("/", response_model=list[QueueJobResponse])
def list_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    active = get_active_account_id(db)
    q = db.query(QueueJob)
    if active is not None:
        q = q.outerjoin(Schedule, Schedule.id == QueueJob.schedule_id).filter(
            or_(
                QueueJob.schedule_id == None,
                Schedule.account_id == active,
                Schedule.account_id == None,
            )
        )
    return q.order_by(QueueJob.created_at.desc()).limit(50).all()


@router.get("/{job_id}", response_model=QueueJobResponse)
def get_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job tidak ditemukan")
    return job


@router.post("/{job_id}/action", response_model=QueueJobResponse)
def control_job(job_id: int, body: QueueAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job tidak ditemukan")

    if job.status in ("done", "error", "canceled"):
        raise HTTPException(400, "Job sudah selesai")

    action = body.action
    if action == "pause":
        job.status = "paused"
    elif action == "resume":
        job.status = "running"
    elif action == "cancel":
        job.status = "canceled"
    else:
        raise HTTPException(400, "Action tidak valid (pause/resume/cancel)")

    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job tidak ditemukan")
    db.delete(job)
    db.commit()
    return {"message": "Job dihapus"}
