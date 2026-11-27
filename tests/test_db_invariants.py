import uuid

import pytest
from app.clock import get_today
from app.identity.models import User, UserRole
from app.prior_auth.models import (
    PriorAuthProcedure,
    PriorAuthRequest,
    ProcedureDecision,
    RequestStatus,
)
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.conftest import approve_all_outcomes, decide_as, get_as, submit_and_claim


def _base_request(seed_data: dict, **overrides) -> PriorAuthRequest:
    values = {
        "uuid": uuid.uuid4(),
        "member_id": seed_data["member"].uuid,
        "practice_id": seed_data["practice"].uuid,
        "submitted_by_user_id": seed_data["office"].uuid,
        "diagnosis_icd10": "J06.9",
        "date_of_service": get_today(),
        "status": RequestStatus.submitted,
    }
    values.update(overrides)
    return PriorAuthRequest(**values)


def test_decided_requires_actor_check(db: Session, seed_data: dict):
    request = _base_request(
        seed_data,
        status=RequestStatus.decided,
        decided_by_user_id=None,
        decided_at=None,
    )
    db.add(request)
    with pytest.raises(IntegrityError):
        db.flush()


def test_decided_requires_timestamp_check(db: Session, seed_data: dict):
    request = _base_request(
        seed_data,
        status=RequestStatus.decided,
        decided_by_user_id=seed_data["reviewer"].uuid,
        decided_at=None,
    )
    db.add(request)
    with pytest.raises(IntegrityError):
        db.flush()


def test_in_review_requires_claimant_check(db: Session, seed_data: dict):
    request = _base_request(
        seed_data,
        status=RequestStatus.in_review,
        claimed_by_user_id=None,
    )
    db.add(request)
    with pytest.raises(IntegrityError):
        db.flush()


def test_procedure_units_at_least_one_check(db: Session, seed_data: dict):
    request = _base_request(seed_data)
    request.procedures.append(PriorAuthProcedure(code="99213", units=0, sequence=1))
    db.add(request)
    with pytest.raises(IntegrityError):
        db.flush()


def test_denied_requires_reason_check(db: Session, seed_data: dict):
    request = _base_request(seed_data)
    request.procedures.append(
        PriorAuthProcedure(
            code="99213",
            units=1,
            sequence=1,
            decision=ProcedureDecision.denied,
            denial_reason=None,
        )
    )
    db.add(request)
    with pytest.raises(IntegrityError):
        db.flush()


def test_denied_rejects_blank_reason_check(db: Session, seed_data: dict):
    request = _base_request(seed_data)
    request.procedures.append(
        PriorAuthProcedure(
            code="99213",
            units=1,
            sequence=1,
            decision=ProcedureDecision.denied,
            denial_reason="   ",
        )
    )
    db.add(request)
    with pytest.raises(IntegrityError):
        db.flush()


def test_member_role_requires_member_id_check(db: Session):
    user = User(
        uuid=uuid.uuid4(),
        email=f"orphan-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.member,
        member_id=None,
        display_name="Orphan Member",
    )
    db.add(user)
    with pytest.raises(IntegrityError):
        db.flush()


def test_http_decide_always_sets_decided_by(client: TestClient, db: Session):
    data = submit_and_claim(client)
    rid = data["uuid"]
    detail = get_as(client, rid, "reviewer")
    procs = detail.json()["procedures"]
    decided = decide_as(client, rid, approve_all_outcomes(procs))
    assert decided.status_code == 200
    row = db.execute(
        text(
            "SELECT decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL "
            "FROM prior_auth_requests WHERE id = :id"
        ),
        {"id": rid},
    ).scalar()
    assert row is True
