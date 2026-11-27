from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

import pytest
from app.clock import get_today
from app.db import get_db
from app.identity.auth import mint_token
from app.identity.models import User, UserRole
from app.identity.schemas import UserContext
from app.prior_auth.models import (
    PriorAuthProcedure,
    PriorAuthRequest,
    ProcedureDecision,
    RequestStatus,
)
from app.prior_auth.schemas import DecideIn, ProcedureDecisionIn
from app.prior_auth.serializers import to_member_out
from app.prior_auth.services.claim import claim_request
from app.prior_auth.services.decide import decide_request
from app.shared.errors import ForbiddenError, NotFoundError, ValidationFailure
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import (
    auth,
    claim_as,
    get_as,
    get_intake_rejection_as,
    make_other_office,
    reassign_as,
    role_headers,
    submit_and_claim,
    submit_as_office,
    submit_ok,
    valid_submit_body,
)


def test_get_db_yields_and_closes():
    gen = get_db()
    session = next(gen)
    assert session is not None
    with contextlib.suppress(StopIteration):
        next(gen)


def test_submit_office_without_practice(db: Session, client: TestClient):
    orphan = User(
        uuid=uuid.uuid4(),
        email=f"orphan-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.provider_office,
        practice_id=None,
        display_name="Orphan Office",
    )
    db.add(orphan)
    db.flush()
    response = client.post(
        "/v1/prior-auths",
        headers=auth(mint_token(orphan)),
        json=valid_submit_body(client.seed),
    )
    from tests.conftest import assert_has_error_code

    assert_has_error_code(
        response,
        "missing_practice",
        field="actor",
        message="Office user must belong to a practice",
    )


@pytest.mark.parametrize(
    ("path_template", "role", "expected"),
    [
        ("/v1/prior-auths/{id}", "office", 404),
        ("/v1/prior-auths/{id}/audit", "admin", 404),
        ("/v1/me/prior-auths/{id}", "member", 404),
    ],
)
def test_router_not_found(client: TestClient, path_template: str, role: str, expected: int):
    path = path_template.format(id=uuid.uuid4())
    response = client.get(path, headers=role_headers(client, role))
    assert response.status_code == expected
    assert response.json()["detail"] == "Prior auth request not found"


def test_claimed_hidden_from_other_reviewer(client: TestClient):
    data = submit_and_claim(client)
    denied = get_as(client, data["uuid"], "reviewer2")
    assert denied.status_code == 403


def test_intake_wrong_practice_hidden(client: TestClient, db: Session):
    other_office = make_other_office(db, name="Other")
    failed = submit_as_office(client, member_id=str(client.seed["unlinked"].uuid))
    cid = failed.json()["correlation_id"]
    hidden = client.get(
        f"/v1/support/intake-rejections/{cid}",
        headers=auth(mint_token(other_office)),
    )
    assert hidden.status_code == 404
    # office owner can still see it
    assert get_intake_rejection_as(client, cid).status_code == 200


def test_claim_not_found(db: Session, seed_data: dict):
    ctx = UserContext(user_id=seed_data["reviewer"].uuid, role=UserRole.reviewer)
    with pytest.raises(NotFoundError):
        claim_request(db, ctx, uuid.uuid4())


def test_decide_edges(db: Session, seed_data: dict, client: TestClient):
    data = submit_and_claim(client)
    rid = uuid.UUID(data["uuid"])
    proc_id = uuid.UUID(data["procedures"][0]["uuid"])
    dummy_outcome = ProcedureDecisionIn(procedure_id=proc_id, decision="approved")
    ctx = UserContext(user_id=seed_data["reviewer"].uuid, role=UserRole.reviewer)

    with pytest.raises(NotFoundError):
        decide_request(db, ctx, uuid.uuid4(), DecideIn(outcomes=[dummy_outcome]))

    with pytest.raises(ValidationFailure) as exc_info:
        decide_request(
            db,
            ctx,
            rid,
            DecideIn(outcomes=[ProcedureDecisionIn(procedure_id=proc_id, decision="maybe")]),
        )
    assert any(e.error_code == "invalid_decision" for e in exc_info.value.errors)

    req = db.get(PriorAuthRequest, rid)
    assert req is not None
    req.claimed_by_user_id = seed_data["reviewer_coi"].uuid
    db.flush()
    coi_ctx = UserContext(user_id=seed_data["reviewer_coi"].uuid, role=UserRole.reviewer)
    with pytest.raises(ForbiddenError):
        decide_request(db, coi_ctx, rid, DecideIn(outcomes=[dummy_outcome]))

    req.claimed_by_user_id = seed_data["reviewer"].uuid
    db.flush()
    other = UserContext(user_id=seed_data["reviewer2"].uuid, role=UserRole.reviewer)
    with pytest.raises(ForbiddenError):
        decide_request(db, other, rid, DecideIn(outcomes=[dummy_outcome]))


def test_reassign_edges(client: TestClient):
    missing = reassign_as(client, str(uuid.uuid4()), client.seed["reviewer"].uuid)
    assert missing.status_code == 404

    created = submit_as_office(client)
    rid = created.json()["uuid"]
    bad_state = reassign_as(client, rid, client.seed["reviewer"].uuid)
    assert bad_state.status_code == 409

    claim_as(client, rid)
    bad_rev = reassign_as(client, rid, client.seed["office"].uuid)
    assert bad_rev.status_code == 422


def test_member_serializer_statuses():
    request = PriorAuthRequest(
        uuid=uuid.uuid4(),
        member_id=uuid.uuid4(),
        practice_id=uuid.uuid4(),
        submitted_by_user_id=uuid.uuid4(),
        diagnosis_icd10="J06.9",
        date_of_service=get_today(),
        status=RequestStatus.submitted,
    )
    request.created_at = datetime.now(UTC)
    request.procedures = [
        PriorAuthProcedure(
            uuid=uuid.uuid4(),
            request_id=request.uuid,
            code="99213",
            units=1,
            sequence=1,
            decision=ProcedureDecision.approved,
        ),
        PriorAuthProcedure(
            uuid=uuid.uuid4(),
            request_id=request.uuid,
            code="99214",
            units=1,
            sequence=2,
            decision=ProcedureDecision.pending,
        ),
    ]
    out = to_member_out(request)
    assert out.procedures[0].status.value == "approved"
    assert out.procedures[1].status.value == "pending"


def test_admin_lists_all(client: TestClient):
    submit_ok(client)
    listed = client.get("/v1/prior-auths", headers=role_headers(client, "admin"))
    assert listed.status_code == 200
    assert len(listed.json()) >= 1


@pytest.mark.parametrize("role", ["reviewer", "admin"])
def test_reviewer_or_admin_can_get_unclaimed(client: TestClient, role: str):
    rid = submit_ok(client)["uuid"]
    assert get_as(client, rid, role).status_code == 200


def test_office_wrong_practice_get(client: TestClient, db: Session):
    other_office = make_other_office(db, name="Elsewhere")
    rid = submit_ok(client)["uuid"]
    response = client.get(
        f"/v1/prior-auths/{rid}",
        headers=auth(mint_token(other_office)),
    )
    assert response.status_code == 404


def test_member_forbidden_on_get_prior_auth(client: TestClient):
    rid = submit_ok(client)["uuid"]
    assert get_as(client, rid, "member").status_code == 403


def test_member_cannot_see_other_members_request(client: TestClient, db: Session):
    rid = submit_ok(client)["uuid"]
    other = User(
        uuid=uuid.uuid4(),
        email=f"mem2-{uuid.uuid4().hex[:6]}@ex.com",
        role=UserRole.member,
        member_id=client.seed["unlinked"].uuid,
        display_name="Other Member",
    )
    db.add(other)
    db.flush()
    response = client.get(
        f"/v1/me/prior-auths/{rid}",
        headers=auth(mint_token(other)),
    )
    assert response.status_code == 404


def test_telemetry_otlp_and_counters(monkeypatch):
    import app.telemetry as tel
    from fastapi import FastAPI

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    # Force a fresh provider path even if the TestClient lifespan already ran.
    tel._providers_ready = False
    tel._sqlalchemy_instrumented = False
    instrumented: list[dict] = []

    class FakeSQLA:
        def instrument(self, **kwargs):
            instrumented.append(kwargs)

    monkeypatch.setattr(tel, "SQLAlchemyInstrumentor", FakeSQLA)
    app = FastAPI()
    with contextlib.suppress(Exception):
        tel.setup_telemetry(app)
    assert instrumented
    assert "engine" in instrumented[0]
    assert instrumented[0].get("skip_dep_check") is True
    tel.record_claim_conflict()
    tel.record_intake_rejection()
    tel._claim_conflict_counter = None
    tel._intake_rejection_counter = None
    tel.record_claim_conflict()
    tel.record_intake_rejection()
    # Second configure is idempotent for providers/SQLAlchemy; still instruments FastAPI.
    tel.configure_telemetry(fastapi_app=FastAPI())
    # Worker path: providers already up, no FastAPI app.
    tel.configure_telemetry()
