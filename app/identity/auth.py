from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.identity.models import User, UserRole, UserStatus
from app.identity.schemas import UserContext

bearer = HTTPBearer(auto_error=False)


def mint_token(user: User, *, hours: int = 24, exp: datetime | None = None) -> str:
    payload = {
        "sub": str(user.uuid),
        "role": user.role.value,
        "org_id": str(user.org_id) if user.org_id else None,
        "email": user.email,
        "exp": exp if exp is not None else datetime.now(UTC) + timedelta(hours=hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> UserContext:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        data = jwt.decode(
            creds.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    try:
        user_id = uuid.UUID(data["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    if user.status == UserStatus.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    if user.status == UserStatus.invited:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not activated")
    return UserContext(
        user_id=user.uuid,
        role=user.role,
        status=user.status,
        org_id=user.org_id,
        email=user.email,
    )


def require_role(*roles: UserRole) -> Callable[..., UserContext]:
    def _dep(ctx: Annotated[UserContext, Depends(get_current_user)]) -> UserContext:
        if ctx.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return ctx

    return _dep
