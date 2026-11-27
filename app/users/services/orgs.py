from __future__ import annotations

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.identity.schemas import UserContext
from app.orgs.models import Organization
from app.shared.errors import FieldError, raise_validation
from app.users.schemas import CreateOrgIn
from app.users.services.common import validate_email


def create_organization(db: Session, admin: UserContext, body: CreateOrgIn) -> Organization:
    errors = validate_email(body.notification_email)
    mapped = [
        FieldError(
            error_code=err.error_code,
            field="notification_email",
            message=err.message,
        )
        for err in errors
    ]
    name = body.name.strip()
    if not name:
        mapped.append(
            FieldError(
                error_code="name_required",
                field="name",
                message="Organization name is required",
            )
        )
    if mapped:
        raise_validation(mapped)

    email = body.notification_email.strip().lower()
    org = Organization(name=name, notification_email=email)
    db.add(org)
    db.flush()
    write_audit(
        db,
        actor_user_id=admin.user_id,
        action="org_create",
        payload={"org_id": str(org.uuid), "name": org.name},
    )
    db.commit()
    db.refresh(org)
    return org
