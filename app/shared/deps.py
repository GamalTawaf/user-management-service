from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.identity.auth import get_current_user, require_role
from app.identity.models import UserRole
from app.identity.schemas import UserContext

_require_admin = require_role(UserRole.admin)
_require_member = require_role(UserRole.member)
_require_admin_or_auditor = require_role(UserRole.admin, UserRole.auditor)
_require_admin_or_member = require_role(UserRole.admin, UserRole.member)

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[UserContext, Depends(get_current_user)]
AdminUser = Annotated[UserContext, Depends(_require_admin)]
MemberUser = Annotated[UserContext, Depends(_require_member)]
AdminOrAuditor = Annotated[UserContext, Depends(_require_admin_or_auditor)]
AdminOrMember = Annotated[UserContext, Depends(_require_admin_or_member)]
