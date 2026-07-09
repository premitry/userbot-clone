"""Targets page (HTML) — gabungan Groups + Channels + Labels dalam satu menu.

Halaman ini hanya me-render templates/targets.html. Semua data & aksi memakai
API backend yang sudah ada (tidak ada logic yang dihapus):
  - /api/groups/        daftar target + POST /api/groups/sync
  - /api/channels/      channel library + sync post
  - /api/labels/        target labels + assign
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import decode_token
from database import get_db
from models import User

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


@router.get("/targets", response_class=HTMLResponse)
def page_targets(request: Request, db: Session = Depends(get_db)):
    user = _check_auth(request, db)
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse(
        "targets.html", {"request": request, "user": user}
    )
