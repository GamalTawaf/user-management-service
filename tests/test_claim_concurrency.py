from __future__ import annotations

from app.identity.models import UserRole
from app.identity.schemas import UserContext
from app.prior_auth.models import PriorAuthRequest, RequestStatus
from app.prior_auth.services.claim import claim_request
from fastapi.testclient import TestClient

from tests.conftest import (
    claim_as,
    race_attempt,
    role_headers,
    run_two_thread_race,
    seed_race_fixture,
    submit_ok,
)


def test_claim_via_http(client: TestClient):
    rid = submit_ok(client)["uuid"]
    queue = client.get("/v1/review-queue", headers=role_headers(client, "reviewer"))
    assert any(r["uuid"] == rid for r in queue.json())
    claimed = claim_as(client, rid)
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "in_review"
    assert claimed.json()["claimed_by_user_id"] == str(client.seed["reviewer"].uuid)

    lost = claim_as(client, rid, role="reviewer2")
    assert lost.status_code == 409


def test_concurrent_claim_exactly_one_wins(engine):
    fixture = seed_race_fixture(engine, status=RequestStatus.submitted, name="Race")
    SessionLocal = fixture["session_factory"]
    request_id = fixture["request_id"]
    r1_id = fixture["reviewer1_id"]
    r2_id = fixture["reviewer2_id"]

    def make_attempt(user_id):
        def _body():
            with SessionLocal() as session:
                ctx = UserContext(user_id=user_id, role=UserRole.reviewer)
                claim_request(session, ctx, request_id)

        return race_attempt(_body)

    outcomes = run_two_thread_race([make_attempt(r1_id), make_attempt(r2_id)])
    assert sorted(outcomes) == ["lost", "won"], outcomes
    with SessionLocal() as db:
        row = db.get(PriorAuthRequest, request_id)
        assert row is not None
        assert row.status == RequestStatus.in_review
        assert row.claimed_by_user_id in {r1_id, r2_id}
