"""Regression tests for final-review Important findings."""

from __future__ import annotations

from app.identity.models import UserRole
from app.identity.schemas import UserContext
from app.prior_auth.models import RequestStatus
from app.prior_auth.schemas import DecideIn, ProcedureDecisionIn
from app.prior_auth.services.decide import decide_request
from fastapi.testclient import TestClient

from tests.conftest import (
    assert_has_error_code,
    decide_as,
    get_intake_rejection_as,
    race_attempt,
    reassign_as,
    run_two_thread_race,
    seed_race_fixture,
    submit_and_claim,
    submit_as_office,
)


def test_duplicate_procedure_outcomes_rejected(client: TestClient):
    data = submit_and_claim(client)
    pid = data["procedures"][0]["uuid"]
    response = decide_as(
        client,
        data["uuid"],
        [
            {"procedure_id": pid, "decision": "approved"},
            {"procedure_id": pid, "decision": "denied", "denial_reason": "x"},
        ],
    )
    assert_has_error_code(
        response,
        "procedures_incomplete",
        field="outcomes",
        message="Decision must cover every procedure exactly once",
    )


def test_reassign_rejects_coi_reviewer(client: TestClient):
    data = submit_and_claim(client)
    response = reassign_as(client, data["uuid"], client.seed["reviewer_coi"].uuid)
    assert_has_error_code(
        response,
        "reviewer_coi",
        field="reviewer_id",
        message="Reviewer has a conflict of interest with this member",
    )


def test_pydantic_units_zero_persists_intake_rejection(client: TestClient):
    response = submit_as_office(client, procedures=[{"code": "99213", "units": 0}])
    payload = assert_has_error_code(
        response,
        "units_too_low",
        field="procedures[0].units",
        message="Units must be at least 1",
    )
    support = get_intake_rejection_as(client, payload["correlation_id"])
    assert support.status_code == 200


def test_concurrent_decide_exactly_one_wins(engine):
    fixture = seed_race_fixture(
        engine,
        status=RequestStatus.in_review,
        claimed_by_reviewer=True,
        name="Lock",
    )
    SessionLocal = fixture["session_factory"]
    request_id = fixture["request_id"]
    proc_id = fixture["procedure_id"]
    reviewer_id = fixture["reviewer1_id"]

    def _body():
        with SessionLocal() as session:
            ctx = UserContext(user_id=reviewer_id, role=UserRole.reviewer)
            body = DecideIn(
                outcomes=[ProcedureDecisionIn(procedure_id=proc_id, decision="approved")]
            )
            decide_request(session, ctx, request_id, body)

    outcomes = run_two_thread_race([race_attempt(_body), race_attempt(_body)])
    assert sorted(outcomes) == ["lost", "won"], outcomes
