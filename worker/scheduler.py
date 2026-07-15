"""APScheduler integration — Auto Share (cron / fixed_times / interval).

Pemilihan akun pengirim per target (account_mode): fixed | random |
round_robin | least_used, berdasarkan relasi account_targets (akun yang join &
boleh kirim) dan worker yang sedang aktif.

Resolusi target mendukung sumber: manual_targets | telegram_folder |
manual_collection (plus legacy label). Duplikat dihilangkan dan target dengan
can_send=false dilewati.
"""

import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from database import SessionLocal
from models import (
    AccountTarget, Group, ManualCollectionMember, Message, Schedule,
    TargetLabelItem, TelegramFolderMember,
)

logger = logging.getLogger(__name__)

APP_TZ = ZoneInfo(settings.APP_TIMEZONE)
scheduler = AsyncIOScheduler(timezone=APP_TZ)


def _next_run(job):
    return getattr(job, "next_run_time", None)


def init_scheduler():
    db = SessionLocal()
    try:
        active = db.query(Schedule).filter(Schedule.is_active == True).all()
        for s in active:
            add_schedule_job(s)
        logger.info("📅 Scheduler loaded: %d active campaigns (timezone=%s)", len(active), settings.APP_TIMEZONE)
    finally:
        db.close()

    if not scheduler.running:
        scheduler.start()


def remove_schedule_job(schedule_id: int):
    prefix = f"schedule_{schedule_id}"
    for job in scheduler.get_jobs():
        if job.id == prefix or job.id.startswith(prefix + "_"):
            try:
                scheduler.remove_job(job.id)
            except Exception:
                logger.debug("Gagal remove job %s", job.id, exc_info=True)


def add_schedule_job(schedule: Schedule):
    remove_schedule_job(schedule.id)

    st = schedule.schedule_type or "cron"
    dow = schedule.days_active or None  # APScheduler day_of_week: 0=mon..6=sun

    if st == "fixed_times":
        times = [t.strip() for t in (schedule.fixed_times or "").split(",") if t.strip()]
        for idx, t in enumerate(times):
            try:
                hh, mm = t.split(":")
                trigger = CronTrigger(hour=int(hh), minute=int(mm), day_of_week=dow, timezone=APP_TZ)
            except Exception:
                logger.warning("Fixed-time tidak valid pada schedule %s: %r", schedule.id, t)
                continue
            job = scheduler.add_job(
                _run_scheduled, trigger=trigger,
                id=f"schedule_{schedule.id}_t{idx}",
                args=[schedule.id], replace_existing=True,
            )
            logger.info("📅 Fixed-times job: %s jam=%s next=%s tz=%s", job.id, t, _next_run(job), settings.APP_TIMEZONE)
        logger.info("📅 Fixed-times loaded: schedule_%s (%s)", schedule.id, schedule.fixed_times)
        return

    if st == "interval":
        mins = schedule.interval_minutes or 60
    job = scheduler.add_job(
            _run_scheduled, trigger=IntervalTrigger(minutes=mins),
            id=f"schedule_{schedule.id}",
            args=[schedule.id], replace_existing=True,
        )
    logger.info("📅 Interval job: schedule_%s (tiap %sm) next=%s tz=%s", schedule.id, mins, _next_run(job), settings.APP_TIMEZONE)
        return

    # default: cron
    parts = (schedule.cron_expression or "").split()
    if len(parts) != 5:
        logger.warning("⚠️  Invalid cron: %s", schedule.cron_expression)
        return
    trigger = CronTrigger(
        minute=parts[0], hour=parts[1], day=parts[2],
        month=parts[3], day_of_week=parts[4], timezone=APP_TZ,
    )
    job = scheduler.add_job(
        _run_scheduled, trigger=trigger,
        id=f"schedule_{schedule.id}",
        args=[schedule.id], replace_existing=True,
    )
    logger.info("📅 Cron job: schedule_%s (%s) next=%s tz=%s", schedule.id, schedule.cron_expression, _next_run(job), settings.APP_TIMEZONE)


def _resolve_targets(db, schedule):
    """Kumpulkan Group target sesuai target_source; dedup + skip can_send=false."""
    src = getattr(schedule, "target_source", None) or ""
    ids = []

    if src == "telegram_folder" and schedule.folder_id:
        items = db.query(TelegramFolderMember).filter(
            TelegramFolderMember.folder_id == schedule.folder_id
        ).all()
        ids = [it.target_id for it in items]
    elif src == "manual_collection" and schedule.collection_id:
        items = db.query(ManualCollectionMember).filter(
            ManualCollectionMember.collection_id == schedule.collection_id
        ).all()
        ids = [it.target_id for it in items]
    elif schedule.label_id:
        items = db.query(TargetLabelItem).filter(
            TargetLabelItem.label_id == schedule.label_id
        ).all()
        ids = [it.group_id for it in items]
    elif schedule.target_group_ids:
        ids = [int(x) for x in schedule.target_group_ids.split(",") if x.strip().isdigit()]
    elif schedule.group_id:
        ids = [schedule.group_id]

    if not ids:
        return []

    rows = db.query(Group).filter(Group.id.in_(ids)).all()
    by_id = {g.id: g for g in rows}
    out = []
    seen = set()
    for i in ids:
        if i in seen:
            continue  # hilangkan duplikat
        seen.add(i)
        g = by_id.get(i)
        if g and g.telegram_id and g.can_send:  # skip target can_send=false
            out.append(g)
    return out


def _eligible_accounts(db, target_id):
    """account_id yang boleh kirim ke target ini DAN worker-nya aktif."""
    from worker.client import get_worker
    rows = db.query(AccountTarget).filter(
        AccountTarget.target_id == target_id,
        AccountTarget.can_send == True,
        AccountTarget.is_joined == True,
    ).all()
    out = []
    for r in rows:
        w = get_worker(r.account_id)
        if w and w.is_running:
            out.append(r.account_id)
    return out


async def _run_scheduled(schedule_id: int):
    """Trigger campaign — gating hari/jam/limit, pilih akun per target, lalu enqueue."""
    from worker.client import get_worker
    from worker.queue_runner import start_campaign_job

    db = SessionLocal()
    try:
        s = db.get(Schedule, schedule_id)
        if not s or not s.is_active:
            return

        now = datetime.now(APP_TZ)

        if s.days_active:
            allowed = [int(x) for x in s.days_active.split(",") if x.strip().isdigit()]
            if allowed and now.weekday() not in allowed:
                return

        if s.start_time and s.end_time:
            cur = now.strftime("%H:%M")
            if not (s.start_time <= cur <= s.end_time):
                return

        today = now.strftime("%Y-%m-%d")
        if s.sent_date != today:
            s.sent_date = today
            s.sent_today = 0
            db.commit()
        if s.max_per_day and (s.sent_today or 0) >= s.max_per_day:
            return

        worker = get_worker()
        if not worker or not worker.is_running:
            logger.warning("⚠️  Bot offline, skip campaign %s", schedule_id)
            return

        groups = _resolve_targets(db, s)
        if not groups:
            logger.warning("⚠️  Campaign %s tanpa target valid", schedule_id)
            return

        if s.random_order:
            random.shuffle(groups)

        msg = db.get(Message, s.message_id) if s.message_id else None
        mode = s.account_mode or "fixed"
        rr = s.rr_index or 0
        usage = {}
        targets = []
        for g in groups:
            elig = _eligible_accounts(db, g.id)
            if elig:
                if mode == "random":
                    acc = random.choice(elig)
                elif mode == "round_robin":
                    acc = elig[rr % len(elig)]
                    rr += 1
                elif mode == "least_used":
                    acc = min(elig, key=lambda a: usage.get(a, 0))
                else:  # fixed
                    acc = s.account_id if (s.account_id and s.account_id in elig) else elig[0]
                usage[acc] = usage.get(acc, 0) + 1
            else:
                w = get_worker(s.account_id) if s.account_id else None
                if not (w and w.is_running):
                    w = get_worker()
                if not w:
                    continue
                acc = w.account_id
            targets.append((int(g.telegram_id), g.title, acc))

        s.rr_index = rr
        s.last_run = datetime.utcnow()
        s.sent_today = (s.sent_today or 0) + 1
        db.commit()

        if not targets:
            logger.warning("⚠️  Campaign %s tanpa akun pengirim aktif", schedule_id)
            return

        await start_campaign_job(schedule=s, targets=targets, msg=msg, worker=worker)

    except Exception as e:
        logger.error("❌ Campaign error: %s", e, exc_info=True)
    finally:
        db.close()
