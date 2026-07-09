"""
Reset / ganti password login dashboard.

Login dashboard disimpan di database (tabel User), bukan di .env.
Gunakan script ini untuk mengganti password admin atau membuat user baru.

Contoh:
    python reset_password.py                    # interaktif
    python reset_password.py admin passbaru123  # langsung
"""

import getpass
import sys

from auth import hash_password
from database import SessionLocal, init_db
from models import User


def set_password(username: str, new_password: str) -> None:
    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.password_hash = hash_password(new_password)
            user.is_active = True
            print(f"✅ Password untuk '{username}' berhasil diganti.")
        else:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(new_password),
                    is_active=True,
                )
            )
            print(f"✅ User '{username}' dibuat dengan password baru.")
        db.commit()
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) >= 3:
        username = sys.argv[1]
        new_password = sys.argv[2]
    else:
        username = input("Username [admin]: ").strip() or "admin"
        new_password = getpass.getpass("Password baru: ").strip()
        confirm = getpass.getpass("Ulangi password: ").strip()
        if new_password != confirm:
            print("❌ Password tidak cocok.")
            sys.exit(1)

    if not new_password:
        print("❌ Password tidak boleh kosong.")
        sys.exit(1)

    set_password(username, new_password)


if __name__ == "__main__":
    main()
