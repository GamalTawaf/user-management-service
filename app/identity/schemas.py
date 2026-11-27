import uuid
from dataclasses import dataclass

from app.identity.models import UserRole


@dataclass(frozen=True)
class UserContext:
    user_id: uuid.UUID
    role: UserRole
    practice_id: uuid.UUID | None = None
    member_id: uuid.UUID | None = None
    email: str = ""
