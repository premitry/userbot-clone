"""JWT authentication utilities."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User

logger = logging.getLogger("auth")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Resolve current user from Bearer header or cookie."""
    token = None

    if credentials:
        token = credentials.credentials
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    username: str = payload.get("sub", "")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return user


def create_default_user(db: Session) -> None:
    """Buat admin awal & paksa ganti password saat login pertama.

    Jika admin lama masih memakai password default 'admin123', paksa juga
    ganti password demi keamanan (tanpa menghapus/mereset akun).
    """
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        db.add(
            User(
                username="admin",
                password_hash=hash_password("admin123"),
                is_active=True,
                must_change_password=True,
            )
        )
        db.commit()
        logger.info("Admin awal dibuat — WAJIB ganti password saat login pertama")
        return

    try:
        if verify_password("admin123", admin.password_hash) and not admin.must_change_password:
            admin.must_change_password = True
            db.commit()
            logger.info("Admin memakai password default — dipaksa ganti saat login berikutnya")
    except Exception as e:
        logger.warning("Cek password default admin dilewati: %s", e)
