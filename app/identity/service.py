from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.auth import mint_token
from app.identity.models import User, UserStatus
from app.identity.passwords import verify_password


def login(db: Session, *, email: str, password: str) -> str:
    normalized = email.strip().lower()
    email_match = User.email == normalized
    stmt = select(User).where(email_match)
    user = db.scalar(stmt)
    if user is None or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if user.status == UserStatus.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    if user.status == UserStatus.invited:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not activated",
        )
    return mint_token(user)
