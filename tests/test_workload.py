import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    approve_all_outcomes,
    claim_as,
    decide_as,
    submit_and_claim,
    submit_ok,
    workload_as,
)


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["reviewer_id"]: row for row in rows}


def test_workload_admin_lists_all_reviewers_at_zero(client: TestClient):
    response = workload_as(client)
    assert response.status_code == 200, response.text
    by_id = _by_id(response.json())
    expected = [
        (client.seed["reviewer"], "Reviewer"),
        (client.seed["reviewer2"], "Reviewer2"),
        (client.seed["reviewer_coi"], "COI Reviewer"),
    ]
    for user, name in expected:
        row = by_id[str(user.uuid)]
        assert row["display_name"] == name
        assert row["open_count"] == 0


@pytest.mark.parametrize("role", ["office", "reviewer", "reviewer2", "member"])
def test_workload_forbidden_for_non_admin(client: TestClient, role: str):
    response = workload_as(client, role=role)
    assert response.status_code == 403


def test_workload_increments_on_claim_decrements_on_decide(client: TestClient):
    reviewer_id = str(client.seed["reviewer"].uuid)
    before = _by_id(workload_as(client).json())
    assert before[reviewer_id]["open_count"] == 0

    claimed = submit_and_claim(client)
    after_claim = _by_id(workload_as(client).json())
    assert after_claim[reviewer_id]["open_count"] == 1

    outcomes = approve_all_outcomes(claimed["procedures"])
    decided = decide_as(client, claimed["uuid"], outcomes)
    assert decided.status_code == 200, decided.text

    after_decide = _by_id(workload_as(client).json())
    assert after_decide[reviewer_id]["open_count"] == 0


def test_workload_counts_per_reviewer(client: TestClient):
    first = submit_ok(client)
    second = submit_ok(client)
    assert claim_as(client, first["uuid"]).status_code == 200
    assert claim_as(client, second["uuid"], role="reviewer2").status_code == 200

    by_id = _by_id(workload_as(client).json())
    assert by_id[str(client.seed["reviewer"].uuid)]["open_count"] == 1
    assert by_id[str(client.seed["reviewer2"].uuid)]["open_count"] == 1
    assert by_id[str(client.seed["reviewer_coi"].uuid)]["open_count"] == 0


def test_workload_requires_auth(client: TestClient):
    response = client.get("/v1/reviewers/workload")
    assert response.status_code == 401
