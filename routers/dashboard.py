"""Dashboard pages (HTML) and stats API.

Menu utama: Dashboard, Accounts, Commands, Auto Share, Targets, Queue, Logs,
Settings. Media dihapus (sudah tergabung di Commands). Statistik & log
di-scope ke AKUN AKTIF.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from active_account import get_active_account_id
from auth import decode_token, get_current_user
from database import get_db
from models import (
    AccountTarget, BotStatus, CommandLog, Group, TelegramAccount, User,
)
from schemas import DashboardStats
from worker.client import get_all_workers

router = APIRouter(tags=["Pages"])
templates = Jinja2Templates(directory="templates")


def _check_auth(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    return db.query(User).filter(User.username == payload.get("sub")).first()


def _gate(user) -> bool:
    """True bila user wajib ganti password dulu (blokir akses halaman lain)."""
    return bool(getattr(user, "must_change_password", False))


def _calc_uptime(bot) -> str:
    if not bot or not bot.uptime_start or not bot.is_running:
        return ""
    delta = datetime.utcnow() - bot.uptime_start
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m}m"


def _log_query(db, active):
    q = db.query(CommandLog)
    if active is not None:
        q = q.filter(or_(
            CommandLog.account_id == active,
            CommandLog.account_id == None,
        ))
    return q


def _group_count(db, active):
    if active is None:
        return db.query(Group).count()
    return db.query(AccountTarget).filter(AccountTarget.account_id == active).count()


def _render(request, db, template):
    user = _check_auth(request, db)
    if not user:
        return RedirectResponse("/login")
    if _gate(user):
        return RedirectResponse("/change-password")
    return templates.TemplateResponse(template, {"request": request, "user": user})


@router.get("/", response_class=HTMLResponse)
def page_root(request: Request, db: Session = Depends(get_db)):
    if not _check_auth(request, db):
        return RedirectResponse("/login")
    return RedirectResponse("/dashboard")


@router.get("/login", response_class=HTMLResponse)
def page_login(request: Request, db: Session = Depends(get_db)):
    if _check_auth(request, db):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/change-password", response_class=HTMLResponse)
def page_change_password(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request, db)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse(
        "change_password.html", {"request": request, "user": user}
    )


@router.get("/dashboard", response_class=HTMLResponse)
def page_dashboard(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request, db)
    if not user:
        return RedirectResponse("/login")
    if _gate(user):
        return RedirectResponse("/change-password")

    bot = db.query(BotStatus).first()
    workers = get_all_workers()
    active_accounts = sum(1 for w in workers.values() if w.is_running)
    active = get_active_account_id(db)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "bot_running": active_accounts > 0,
        "active_accounts": active_accounts,
        "total_accounts": db.query(TelegramAccount).count(),
        "uptime": _calc_uptime(bot),
        "total_groups": _group_count(db, active),
        "total_commands": _log_query(db, active).count(),
        "total_errors": _log_query(db, active).filter(
            CommandLog.status == "failed"
        ).count(),
        "recent_logs": _log_query(db, active)
            .order_by(CommandLog.executed_at.desc())
            .limit(10)
            .all(),
    })


@router.get("/commands", response_class=HTMLResponse)
def page_commands(request: Request, db: Session = Depends(get_db)):
    return _render(request, db, "messages.html")


@router.get("/messages", response_class=HTMLResponse)
def page_messages(request: Request, db: Session = Depends(get_db)):
    # Alias lama → arahkan ke /commands
    return RedirectResponse("/commands")


@router.get("/media", response_class=HTMLResponse)
def page_media(request: Request, db: Session = Depends(get_db)):
    # Menu Media dihapus — media sudah tergabung di Commands
    return RedirectResponse("/commands#media")


@router.get("/campaign", response_class=HTMLResponse)
def page_campaign(request: Request, db: Session = Depends(get_db)):
    return _render(request, db, "schedules.html")


@router.get("/auto-share", response_class=HTMLResponse)
def page_autoshare(request: Request, db: Session = Depends(get_db)):
    return _render(request, db, "schedules.html")


@router.get("/schedules", response_class=HTMLResponse)
def page_schedules(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse("/auto-share")


@router.get("/queue", response_class=HTMLResponse)
def page_queue(request: Request, db: Session = Depends(get_db)):
    return _render(request, db, "queue.html")


@router.get("/logs", response_class=HTMLResponse)
def page_logs(request: Request, db: Session = Depends(get_db)):
    return _render(request, db, "logs.html")


@router.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request, db: Session = Depends(get_db)):
    return _render(request, db, "settings.html")


@router.get("/groups", response_class=HTMLResponse)
def page_groups(request: Request, db: Session = Depends(get_db)):
    # Groups digabung ke Targets
    return RedirectResponse("/targets")


@router.get("/channels", response_class=HTMLResponse)
def page_channels(request: Request, db: Session = Depends(get_db)):
    # Channels digabung ke Targets
    return RedirectResponse("/targets#channels")


@router.get("/labels", response_class=HTMLResponse)
def page_labels(request: Request, db: Session = Depends(get_db)):
    # Labels digabung ke Targets
    return RedirectResponse("/targets#labels")


@router.get("/accounts", response_class=HTMLResponse)
def page_accounts(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request, db)
    if not user:
        return RedirectResponse("/login")
    if _gate(user):
        return RedirectResponse("/change-password")

    accounts = db.query(TelegramAccount).order_by(
        TelegramAccount.added_at.desc()
    ).all()

    workers = get_all_workers()
    for acc in accounts:
        w = workers.get(acc.id)
        acc.is_connected = w.is_running if w else False

    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "user": user,
        "accounts": accounts,
    })


@router.get("/api/dashboard/stats")
def api_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bot = db.query(BotStatus).first()
    workers = get_all_workers()
    active_accounts = sum(1 for w in workers.values() if w.is_running)
    active = get_active_account_id(db)

    return DashboardStats(
        bot_running=active_accounts > 0,
        active_accounts=active_accounts,
        uptime=_calc_uptime(bot) or None,
        total_groups=_group_count(db, active),
        total_commands=_log_query(db, active).count(),
        total_errors=_log_query(db, active).filter(
            CommandLog.status == "failed"
        ).count(),
        recent_logs=_log_query(db, active)
            .order_by(CommandLog.executed_at.desc())
            .limit(10)
            .all(),
    )
