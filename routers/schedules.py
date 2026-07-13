"""Auto Share campaign CRUD endpoints (mode cron / fixed_times / interval).

Sumber target: manual_targets | telegram_folder | manual_collection (legacy: label).
Campaign di-scope ke AKUN AKTIF: list hanya menampilkan campaign milik akun
aktif (+ legacy tanpa akun), dan create menempel ke akun aktif bila account_id
tidak diisi.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import Schedule, User
from schemas import ScheduleCreate, ScheduleResponse, ScheduleToggle
from worker.scheduler import add_schedule_job, remove_schedule_job

router = APIRouter(prefix="/api/schedules", tags=["Schedules"])


@router.get("/", response_model=list[ScheduleResponse])
def list_schedules(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    active = get_active_account_id(db)
    q = db.query(Schedule)
    if active is not None:
        q = q.filter(or_(
            Schedule.account_id == active,
            Schedule.account_id == None,
        ))
    return q.order_by(Schedule.created_at.desc()).all()


@router.post("/", response_model=ScheduleResponse)
def create_schedule(data: ScheduleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    src = data.target_source or ("label" if data.label_id else "manual_targets")

    target_csv = None
    primary = None
    if src == "telegram_folder":
        if not data.folder_id:
            raise HTTPException(400, "Pilih folder Telegram")
    elif src == "manual_collection":
        if not data.collection_id:
            raise HTTPException(400, "Pilih manual collection")
    elif data.label_id:
        src = "label"
    else:
        targets = list(data.target_group_ids or [])
        if not targets and data.group_id:
            targets = [data.group_id]
        targets = [t for t in targets if t]
        if not targets:
            raise HTTPException(400, "Pilih sumber target (manual, folder, atau collection)")
        target_csv = ",".join(str(t) for t in targets)
        primary = targets[0]
        src = "manual_targets"

    st = data.schedule_type or "cron"
    if st == "cron" and not data.cron_expression:
        raise HTTPException(400, "Cron expression wajib untuk mode cron")
    if st == "fixed_times" and not data.fixed_times:
        raise HTTPException(400, "Isi minimal satu jam untuk mode fixed_times")
    if st == "interval" and not data.interval_minutes:
        raise HTTPException(400, "Isi interval (menit) untuk mode interval")

    fixed_csv = ",".join(data.fixed_times) if data.fixed_times else None
    days_csv = ",".join(str(d) for d in data.days_active) if data.days_active else None

    acc_id = data.account_id if data.account_id else get_active_account_id(db)

    schedule = Schedule(
        name=data.name,
        message_id=data.message_id,
        target_source=src,
        folder_id=data.folder_id,
        collection_id=data.collection_id,
        target_group_ids=target_csv,
        label_id=data.label_id,
        schedule_type=st,
        cron_expression=data.cron_expression,
        fixed_times=fixed_csv,
        interval_minutes=data.interval_minutes,
        days_active=days_csv,
        start_time=data.start_time,
        end_time=data.end_time,
        delay_seconds=data.delay_seconds or 0,
        random_delay_min=data.random_delay_min or 0,
        random_delay_max=data.random_delay_max or 0,
        random_order=bool(data.random_order),
        random_message=bool(data.random_message),
        max_per_day=data.max_per_day,
        account_id=acc_id,
        account_mode=data.account_mode or "fixed",
        command=data.command,
        message_text=data.message_text,
        image_url=data.image_url,
        group_id=primary,
        is_active=True,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    if schedule.is_active:
        add_schedule_job(schedule)

    return schedule


@router.put("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(schedule_id: int, data: ScheduleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule tidak ditemukan")

    src = data.target_source or ("label" if data.label_id else "manual_targets")
    target_csv = None
    primary = None
    if src == "telegram_folder":
        if not data.folder_id:
            raise HTTPException(400, "Pilih folder Telegram")
    elif src == "manual_collection":
        if not data.collection_id:
            raise HTTPException(400, "Pilih manual collection")
    elif data.label_id:
        src = "label"
    else:
        targets = list(data.target_group_ids or [])
        if not targets and data.group_id:
            targets = [data.group_id]
        targets = [t for t in targets if t]
        if not targets:
            raise HTTPException(400, "Pilih sumber target (manual, folder, atau collection)")
        target_csv = ",".join(str(t) for t in targets)
        primary = targets[0]
        src = "manual_targets"

    st = data.schedule_type or "cron"
    if st == "cron" and not data.cron_expression:
        raise HTTPException(400, "Cron expression wajib untuk mode cron")
    if st == "fixed_times" and not data.fixed_times:
        raise HTTPException(400, "Isi minimal satu jam untuk mode fixed_times")
    if st == "interval" and not data.interval_minutes:
        raise HTTPException(400, "Isi interval (menit) untuk mode interval")

    schedule.name = data.name
    schedule.message_id = data.message_id
    schedule.target_source = src
    schedule.folder_id = data.folder_id
    schedule.collection_id = data.collection_id
    schedule.target_group_ids = target_csv
    schedule.label_id = data.label_id
    schedule.schedule_type = st
    schedule.cron_expression = data.cron_expression
    schedule.fixed_times = ",".join(data.fixed_times) if data.fixed_times else None
    schedule.interval_minutes = data.interval_minutes
    schedule.days_active = ",".join(str(d) for d in data.days_active) if data.days_active else None
    schedule.start_time = data.start_time
    schedule.end_time = data.end_time
    schedule.delay_seconds = data.delay_seconds or 0
    schedule.random_delay_min = data.random_delay_min or 0
    schedule.random_delay_max = data.random_delay_max or 0
    schedule.random_order = bool(data.random_order)
    schedule.random_message = bool(data.random_message)
    schedule.max_per_day = data.max_per_day
    if data.account_id is not None:
        schedule.account_id = data.account_id
    schedule.account_mode = data.account_mode or "fixed"
    schedule.command = data.command
    schedule.message_text = data.message_text
    schedule.image_url = data.image_url
    schedule.group_id = primary

    db.commit()
    db.refresh(schedule)

    # Reload job agar perubahan langsung berlaku
    remove_schedule_job(schedule.id)
    if schedule.is_active:
        add_schedule_job(schedule)

    return schedule


@router.put("/{schedule_id}/toggle", response_model=ScheduleResponse)
def toggle_schedule(schedule_id: int, data: ScheduleToggle, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule tidak ditemukan")

    schedule.is_active = data.is_active
    db.commit()
    db.refresh(schedule)

    if data.is_active:
        add_schedule_job(schedule)
    else:
        remove_schedule_job(schedule.id)

    return schedule


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule tidak ditemukan")

    remove_schedule_job(schedule.id)
    db.delete(schedule)
    db.commit()
    return {"message": "Schedule dihapus"}
