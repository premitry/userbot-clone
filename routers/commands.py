"""Command execution endpoints + logs (search & export CSV).

Logs di-scope ke AKUN AKTIF (log tanpa akun/legacy tetap tampil).
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo
from config import settings

from active_account import get_active_account_id
from auth import get_current_user
from database import get_db
from models import CommandLog, User
from schemas import CommandExecute, CommandLogResponse
from worker.client import get_worker

router = APIRouter(prefix="/api/commands", tags=["Commands"])


@router.post("/execute")
async def execute_command(
    cmd: CommandExecute,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    worker = get_worker()
    if not worker or not worker.is_running:
        raise HTTPException(503, "Bot worker tidak aktif")

    log = CommandLog(
        command=cmd.command,
        target_group=cmd.target_group_id,
        message=cmd.message,
        status="pending",
        executed_at=datetime.now(ZoneInfo(settings.APP_TIMEZONE)).replace(tzinfo=None),
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        if cmd.command == "pay":
            from worker.commands.pay import execute_pay
            await execute_pay(worker.client, cmd.target_group_id, cmd.message)
        elif cmd.command == "share":
            from worker.commands.share import execute_share
            await execute_share(worker.client, cmd.target_group_id, cmd.message)
        elif cmd.command == "qris":
            from worker.commands.qris import execute_qris
            await execute_qris(
                worker.client, cmd.target_group_id, cmd.message, cmd.image_url
            )
        else:
            raise HTTPException(400, f"Command '{cmd.command}' tidak dikenal")

        log.status = "success"
    except HTTPException:
        raise
    except Exception as e:
        log.status = "failed"
        log.error = str(e)

    db.commit()
    return {"status": log.status, "log_id": log.id, "error": log.error}


def _apply_filters(query, q, status, source):
    if q:
        like = "%" + q + "%"
        query = query.filter(or_(
            CommandLog.command.ilike(like),
            CommandLog.target_group.ilike(like),
            CommandLog.account_name.ilike(like),
            CommandLog.message.ilike(like),
            CommandLog.error.ilike(like),
        ))
    if status:
        query = query.filter(CommandLog.status == status)
    if source:
        query = query.filter(CommandLog.source == source)
    return query


def _scope_active(query, db):
    active = get_active_account_id(db)
    if active is not None:
        query = query.filter(or_(
            CommandLog.account_id == active,
            CommandLog.account_id == None,
        ))
    return query


@router.get("/logs", response_model=list[CommandLogResponse])
def get_logs(
    limit: int = 100,
    q: str = None,
    status: str = None,
    source: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = _apply_filters(db.query(CommandLog), q, status, source)
    query = _scope_active(query, db)
    return query.order_by(CommandLog.executed_at.desc()).limit(limit).all()


@router.get("/logs/export")
def export_logs(
    q: str = None,
    status: str = None,
    source: str = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = _apply_filters(db.query(CommandLog), q, status, source)
    query = _scope_active(query, db)
    rows = query.order_by(CommandLog.executed_at.desc()).limit(5000).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "executed_at", "command", "target_group",
        "account_name", "source", "status", "message", "error",
    ])
    for r in rows:
        writer.writerow([
            r.id,
            r.executed_at.isoformat() if r.executed_at else "",
            r.command or "",
            r.target_group or "",
            r.account_name or "",
            r.source or "",
            r.status or "",
            (r.message or "").replace("\n", " "),
            (r.error or "").replace("\n", " "),
        ])
    buf.seek(0)
    headers = {"Content-Disposition": "attachment; filename=command_logs.csv"}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)
