"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from auth import create_access_token, verify_password, get_current_user
from database import get_db
from models import User
from schemas import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Username atau password salah")

    token = create_access_token(data={"sub": user.username})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "must_change_password": bool(user.must_change_password),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user (for sidebar display)."""
    return {
        "username": user.username,
        "is_active": user.is_active,
        "must_change_password": bool(user.must_change_password),
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out"}
