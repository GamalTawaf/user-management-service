from app.master_data.models import ReviewerMemberConflict
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import claim_as, get_as, role_headers, submit_ok

COI_DETAIL = "Conflict of interest with this member"


def _queue_ids(client: TestClient, role: str) -> list[str]:
    response = client.get("/v1/review-queue", headers=role_headers(client, role))
    assert response.status_code == 200, response.text
    return [row["uuid"] for row in response.json()]


def test_coi_reviewer_cannot_read_request(client: TestClient):
    """COI must hide the chart, not just block the decision."""
    rid = submit_ok(client, clinical_note="SECRET PHI NOTE")["uuid"]
    response = get_as(client, rid, "reviewer_coi")
    assert response.status_code == 403
    assert response.json()["detail"] == COI_DETAIL
    assert "SECRET PHI NOTE" not in response.text


def test_coi_request_is_hidden_from_review_queue(client: TestClient):
    rid = submit_ok(client)["uuid"]
    assert rid not in _queue_ids(client, "reviewer_coi")
    assert rid in _queue_ids(client, "reviewer")


def test_coi_reviewer_cannot_claim(client: TestClient):
    rid = submit_ok(client)["uuid"]
    response = claim_as(client, rid, role="reviewer_coi")
    assert response.status_code == 403
    assert response.json()["detail"] == "Conflict of interest with this member"


def test_coi_is_member_specific(client: TestClient, db: Session):
    """Conflict on another member must not block claim of this request's member."""
    db.add(
        ReviewerMemberConflict(
            reviewer_user_id=client.seed["reviewer2"].uuid,
            member_id=client.seed["unlinked"].uuid,
        )
    )
    db.flush()
    rid = submit_ok(client)["uuid"]
    response = claim_as(client, rid, role="reviewer2")
    assert response.status_code == 200, response.text
