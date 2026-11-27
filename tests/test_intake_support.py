from fastapi.testclient import TestClient

from tests.conftest import get_intake_rejection_as, role_headers, submit_as_office


def test_support_lookup_by_correlation_id(client: TestClient):
    failed = submit_as_office(client, member_id=str(client.seed["unlinked"].uuid))
    assert failed.status_code == 422
    cid = failed.json()["correlation_id"]

    for role in ("office", "admin"):
        support = get_intake_rejection_as(client, cid, role=role)
        assert support.status_code == 200, support.text
        if role == "office":
            data = support.json()
            assert data["correlation_id"] == cid
            assert data["field_errors"]

    missing = client.get(
        "/v1/support/intake-rejections/does-not-exist",
        headers=role_headers(client, "office"),
    )
    assert missing.status_code == 404
