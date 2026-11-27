import uuid
from dataclasses import dataclass

from app.identity.models import UserRole, UserStatus


@dataclass(frozen=True)
class UserContext:
    user_id: uuid.UUID
    role: UserRole
    status: UserStatus
    org_id: uuid.UUID | None = None
    email: str = ""
