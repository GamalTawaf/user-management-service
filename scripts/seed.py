#!/usr/bin/env -S uv run python
"""Seed synthetic master data and print JWT tokens for local demos."""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.clock import get_today
from app.db import SessionLocal, engine
from app.identity.auth import mint_token
from app.identity.models import User, UserRole
from app.master_data.models import (
    Coverage,
    Member,
    PatientPracticeLink,
    Practice,
    ReviewerMemberConflict,
)
from sqlalchemy import select

# Stable UUIDs for demos / Postman env
PRACTICE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
MEMBER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
MEMBER_UNLINKED_ID = uuid.UUID("22222222-2222-2222-2222-222222222299")
OFFICE_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
REVIEWER_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
REVIEWER_COI_ID = uuid.UUID("44444444-4444-4444-4444-444444444455")
ADMIN_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
MEMBER_USER_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
AUDITOR_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")


def seed() -> dict[str, str]:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.uuid == OFFICE_ID)):
            users = {
                "office": db.get(User, OFFICE_ID),
                "reviewer": db.get(User, REVIEWER_ID),
                "reviewer_coi": db.get(User, REVIEWER_COI_ID),
                "admin": db.get(User, ADMIN_ID),
                "member": db.get(User, MEMBER_USER_ID),
                "auditor": db.get(User, AUDITOR_ID),
            }
        else:
            practice = Practice(
                uuid=PRACTICE_ID,
                name="Riverside Clinic",
                notification_email="office@riverside.example.com",
            )
            member = Member(uuid=MEMBER_ID, external_id="M-1001", full_name="Alex Member")
            unlinked = Member(
                uuid=MEMBER_UNLINKED_ID, external_id="M-1099", full_name="Unlinked Patient"
            )
            db.add_all([practice, member, unlinked])
            db.flush()
            db.add(PatientPracticeLink(member_id=MEMBER_ID, practice_id=PRACTICE_ID))
            today = get_today()
            db.add(
                Coverage(
                    member_id=MEMBER_ID,
                    payer_name="Synthetic Payer",
                    effective_from=today - timedelta(days=30),
                    effective_to=today + timedelta(days=400),
                )
            )
            office = User(
                uuid=OFFICE_ID,
                email="office@example.com",
                role=UserRole.provider_office,
                practice_id=PRACTICE_ID,
                display_name="Office User",
            )
            reviewer = User(
                uuid=REVIEWER_ID,
                email="reviewer@example.com",
                role=UserRole.reviewer,
                display_name="Reviewer One",
            )
            reviewer_coi = User(
                uuid=REVIEWER_COI_ID,
                email="reviewer.coi@example.com",
                role=UserRole.reviewer,
                display_name="Reviewer COI",
            )
            admin = User(
                uuid=ADMIN_ID,
                email="admin@example.com",
                role=UserRole.ops_admin,
                display_name="Ops Admin",
            )
            member_user = User(
                uuid=MEMBER_USER_ID,
                email="member@example.com",
                role=UserRole.member,
                member_id=MEMBER_ID,
                display_name="Alex Member",
            )
            auditor = User(
                uuid=AUDITOR_ID,
                email="auditor@example.com",
                role=UserRole.auditor,
                display_name="Auditor",
            )
            db.add_all([office, reviewer, reviewer_coi, admin, member_user, auditor])
            db.flush()
            db.add(ReviewerMemberConflict(reviewer_user_id=REVIEWER_COI_ID, member_id=MEMBER_ID))
            db.commit()
            users = {
                "office": office,
                "reviewer": reviewer,
                "reviewer_coi": reviewer_coi,
                "admin": admin,
                "member": member_user,
                "auditor": auditor,
            }

        if users.get("auditor") is None:
            auditor = User(
                uuid=AUDITOR_ID,
                email="auditor@example.com",
                role=UserRole.auditor,
                display_name="Auditor",
            )
            db.add(auditor)
            db.commit()
            users["auditor"] = auditor

        tokens = {k: mint_token(v) for k, v in users.items() if v is not None}
        return tokens


def main() -> None:
    # ensure engine reachable
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")
    tokens = seed()
    print("Seeded. JWT tokens:")
    for role, token in tokens.items():
        print(f"  {role}: {token}")


if __name__ == "__main__":
    main()
