from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.identity.auth import get_current_user, require_role
from app.identity.models import UserRole
from app.identity.schemas import UserContext

_require_office = require_role(UserRole.provider_office)
_require_reviewer = require_role(UserRole.reviewer)
_require_admin = require_role(UserRole.ops_admin)
_require_member = require_role(UserRole.member)
_require_office_or_admin = require_role(UserRole.provider_office, UserRole.ops_admin)
_require_admin_or_auditor = require_role(UserRole.ops_admin, UserRole.auditor)
_require_office_admin_or_auditor = require_role(
    UserRole.provider_office, UserRole.ops_admin, UserRole.auditor
)

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[UserContext, Depends(get_current_user)]
OfficeUser = Annotated[UserContext, Depends(_require_office)]
ReviewerUser = Annotated[UserContext, Depends(_require_reviewer)]
AdminUser = Annotated[UserContext, Depends(_require_admin)]
MemberUser = Annotated[UserContext, Depends(_require_member)]
OfficeOrAdmin = Annotated[UserContext, Depends(_require_office_or_admin)]
AdminOrAuditor = Annotated[UserContext, Depends(_require_admin_or_auditor)]
OfficeAdminOrAuditor = Annotated[UserContext, Depends(_require_office_admin_or_auditor)]
