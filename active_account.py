"""Helper 'Akun Aktif' — scope command/target/dll berdasarkan akun terpilih.

Akun aktif disimpan di AppSetting (key 'active_account_id'). Semua halaman
(Commands, Targets, Auto Share, Queue, Logs, Dashboard) memfilter data
berdasarkan akun aktif ini. Jika belum diset / akun sudah dihapus, otomatis
jatuh ke akun pertama.
"""

from sqlalchemy.orm import Session

from models import AppSetting, TelegramAccount

ACTIVE_KEY = "active_account_id"


def _write(db: Session, account_id: int) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == ACTIVE_KEY).first()
    if row:
        row.value = str(account_id)
    else:
        db.add(AppSetting(key=ACTIVE_KEY, value=str(account_id)))
    db.commit()


def get_active_account_id(db: Session):
    """Kembalikan id akun aktif; fallback ke akun pertama; None jika tak ada akun."""
    row = db.query(AppSetting).filter(AppSetting.key == ACTIVE_KEY).first()
    if row and row.value:
        try:
            aid = int(row.value)
        except (TypeError, ValueError):
            aid = None
        if aid and db.query(TelegramAccount).filter(TelegramAccount.id == aid).first():
            return aid

    acc = db.query(TelegramAccount).order_by(TelegramAccount.id).first()
    if acc:
        _write(db, acc.id)
        return acc.id
    return None


def set_active_account_id(db: Session, account_id: int):
    """Set akun aktif. Return id bila valid, None bila akun tak ditemukan."""
    acc = db.query(TelegramAccount).filter(TelegramAccount.id == account_id).first()
    if not acc:
        return None
    _write(db, account_id)
    return account_id
