from __future__ import annotations

import uuid

from app.audit.models import AuditEvent
from app.identity.models import User, UserRole
from app.identity.schemas import UserContext
from app.prior_auth.models import PriorAuthRequest, RequestStatus
from app.prior_auth.services.reassign import reassign_request
from sqlalchemy import select

from tests.conftest import race_attempt, run_two_thread_race, seed_race_fixture


def test_concurrent_reassign_audit_from_chain(engine):
    """Row lock before capturing previous so concurrent audits form a from→to chain.

    Without SELECT … FOR UPDATE both races can audit from=original holder.
    """
    fixture = seed_race_fixture(
        engine,
        status=RequestStatus.in_review,
        claimed_by_reviewer=True,
        name="Reassign",
    )
    SessionLocal = fixture["session_factory"]
    request_id = fixture["request_id"]
    original = fixture["reviewer1_id"]
    r2_id = fixture["reviewer2_id"]

    with SessionLocal() as db:
        admin = User(
            uuid=uuid.uuid4(),
            email=f"a-{uuid.uuid4().hex[:6]}@ex.com",
            role=UserRole.ops_admin,
            display_name="A",
        )
        r3 = User(
            uuid=uuid.uuid4(),
            email=f"r3-{uuid.uuid4().hex[:6]}@ex.com",
            role=UserRole.reviewer,
            display_name="R3",
        )
        db.add_all([admin, r3])
        db.commit()
        admin_id = admin.uuid
        r3_id = r3.uuid

    def make_attempt(reviewer_id):
        def _body():
            with SessionLocal() as session:
                ctx = UserContext(user_id=admin_id, role=UserRole.ops_admin)
                reassign_request(session, ctx, request_id, reviewer_id)

        return race_attempt(_body)

    outcomes = run_two_thread_race([make_attempt(r2_id), make_attempt(r3_id)])
    assert outcomes.count("won") == 2, outcomes

    with SessionLocal() as db:
        row = db.get(PriorAuthRequest, request_id)
        assert row is not None
        assert row.claimed_by_user_id in {r2_id, r3_id}
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.request_id == request_id,
                AuditEvent.action == "reassign",
            )
        ).all()
        assert len(events) == 2
        froms = {e.payload["from"] for e in events}
        # Locking: second reassign sees the first winner as previous holder.
        assert froms == {str(original), str(r2_id)} or froms == {
            str(original),
            str(r3_id),
        }, froms
