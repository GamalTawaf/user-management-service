from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.identity.auth import get_current_user, require_role
from app.identity.models import UserRole
from app.identity.schemas import UserContext

_require_admin = require_role(UserRole.admin)
_require_admin_or_auditor = require_role(UserRole.admin, UserRole.auditor)

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[UserContext, Depends(get_current_user)]
AdminUser = Annotated[UserContext, Depends(_require_admin)]
AdminOrAuditor = Annotated[UserContext, Depends(_require_admin_or_auditor)]
