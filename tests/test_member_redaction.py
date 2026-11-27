from fastapi.testclient import TestClient

from tests.conftest import (
    claim_as,
    decide_as,
    get_audit_as,
    role_headers,
    submit_and_claim,
    submit_ok,
)


def test_member_get_strips_note_and_denial_reason(client: TestClient):
    data = submit_and_claim(client, clinical_note="SECRET NOTE")
    rid = data["uuid"]
    decide_as(
        client,
        rid,
        [
            {
                "procedure_id": data["procedures"][0]["uuid"],
                "decision": "denied",
                "denial_reason": "Not covered experimentally",
            }
        ],
    )

    member = client.get(
        f"/v1/me/prior-auths/{rid}",
        headers=role_headers(client, "member"),
    )
    assert member.status_code == 200, member.text
    body = member.json()
    assert "clinical_note" not in body
    assert "denial_reason" not in str(body)
    assert body["procedures"][0]["status"] == "not_approved"

    listed = client.get("/v1/me/prior-auths", headers=role_headers(client, "member"))
    assert listed.status_code == 200
    assert any(r["uuid"] == rid for r in listed.json())


def test_admin_audit_trail(client: TestClient):
    rid = submit_ok(client)["uuid"]
    claim_as(client, rid)
    audit = get_audit_as(client, rid)
    assert audit.status_code == 200
    events = audit.json()
    actions = {e["action"] for e in events}
    assert "submit" in actions
    assert "claim" in actions
    claim_event = next(e for e in events if e["action"] == "claim")
    assert claim_event["payload"]["request_id"] == rid
    assert claim_event["payload"]["reviewer_id"] == str(client.seed["reviewer"].uuid)
    submit_event = next(e for e in events if e["action"] == "submit")
    assert submit_event["payload"]["request_id"] == rid
    assert "member_id" in submit_event["payload"]
    assert "procedure_codes" in submit_event["payload"]
