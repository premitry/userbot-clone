"""Queue runner — eksekusi campaign Auto Share sebagai job antrian.

Mendukung pause / resume / cancel, pemilihan akun pengirim per target (via
tuple target), dan Random Message (acak Message aktif tiap kirim).
"""

import asyncio
import random
from datetime import datetime

from database import SessionLocal
from models import CommandLog, Message, QueueJob
from zoneinfo import ZoneInfo
from config import settings


def _now_local():
    return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).replace(tzinfo=None)


def _classify_error(e: Exception) -> str:
    low = str(e).lower()
    if "flood" in low:
        return "floodwait"
    if any(k in low for k in ("permission", "forbidden", "chat_admin", "chat_write", "banned", "restricted")):
        return "no_permission"
    return "failed"


def _random_active_message(db):
    msgs = db.query(Message).filter(Message.is_active == True).all()
    return random.choice(msgs) if msgs else None


async def start_campaign_job(schedule, targets, msg, worker=None) -> int:
    """Buat QueueJob lalu jalankan di background. Return job_id.

    targets: list of (chat_id, title, account_id) atau (chat_id, title).
    """
    db = SessionLocal()
    try:
        job = QueueJob(
            name=schedule.name,
            schedule_id=schedule.id,
            message_id=schedule.message_id,
            status="waiting",
            total=len(targets),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    finally:
        db.close()

    asyncio.create_task(_run(
        job_id=job_id,
        targets=targets,
        message_id=schedule.message_id,
        fallback_text=schedule.message_text,
        cmd_name=(schedule.command or (msg.command if msg else "auto")),
        delay_fixed=schedule.delay_seconds or 0,
        rmin=schedule.random_delay_min or 0,
        rmax=schedule.random_delay_max or 0,
        random_message=bool(schedule.random_message),
        source="auto",
    ))
    return job_id


async def _sleep_between(delay_fixed, rmin, rmax):
    if rmax and rmax >= rmin and rmax > 0:
        await asyncio.sleep(random.randint(rmin, rmax))
    elif delay_fixed > 0:
        await asyncio.sleep(delay_fixed)


async def _run(job_id, targets, message_id, fallback_text, cmd_name,
              delay_fixed, rmin, rmax, random_message=False, source="auto"):
    from worker.client import get_worker
    from worker.flood_handler import safe_send
    from worker.message_sender import send_message_to_chat

    db = SessionLocal()
    try:
        job = db.get(QueueJob, job_id)
        if not job:
            return
        job.status = "running"
        db.commit()

        base_msg = db.get(Message, message_id) if message_id else None

        for i, tgt in enumerate(targets):
            if len(tgt) >= 3:
                chat_id, title, account_id = tgt[0], tgt[1], tgt[2]
            else:
                chat_id, title, account_id = tgt[0], tgt[1], None

            db.refresh(job)
            if job.status == "canceled":
                break
            while job.status == "paused":
                await asyncio.sleep(2)
                db.refresh(job)
            if job.status == "canceled":
                break

            if i > 0:
                await _sleep_between(delay_fixed, rmin, rmax)

            worker = get_worker(account_id) if account_id else None
            if not (worker and worker.is_running):
                worker = get_worker()

            job.current_target = title
            db.commit()

            msg = _random_active_message(db) if random_message else base_msg

            log = CommandLog(
                command=f"auto_{cmd_name}",
                target_group=title,
                account_name=(worker.display_name if worker else ""),
                account_id=(worker.account_id if worker else None),
                source=source,
                status="pending",
                message=(msg.name if msg else fallback_text),
                executed_at=_now_local(),
            )
            db.add(log)
            db.commit()

            try:
                if not (worker and worker.is_running):
                    raise ValueError("Tidak ada akun aktif untuk target ini")
                if msg:
                    await send_message_to_chat(worker.client, chat_id, msg, db)
                elif fallback_text:
                    await safe_send(worker.client, chat_id, fallback_text)
                else:
                    raise ValueError("Campaign tanpa Message/teks")
                log.status = "success"
                job.success_count = (job.success_count or 0) + 1
            except Exception as e:
                log.status = _classify_error(e)
                log.error = str(e)
                job.failed_count = (job.failed_count or 0) + 1
                job.error = f"{log.status}: {e}"  # surface alasan gagal ke QueueJob

            job.completed = i + 1
            db.commit()

        db.refresh(job)
        if job.status != "canceled":
            job.status = "done"
        job.current_target = None
        job.finished_at = _now_local()
        db.commit()

    except Exception as e:
        try:
            job = db.get(QueueJob, job_id)
            if job:
                job.status = "error"
                job.error = str(e)
                job.finished_at = _now_local()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
